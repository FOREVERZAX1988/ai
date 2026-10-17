"""Background chat jobs — survive browser refresh/disconnect."""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from typing import Any, Callable

from openpilot.common.params import Params

from ai.core.chat.detect import content_looping as _content_looping, content_truncated as _content_truncated
from ai.core.chat.runner import ChatCancelled, run_chat_loop
from ai.agents.orchestrator import run_chat_with_agents

_MAX_JOBS = 20
_JOB_TTL_SEC = 3600
# 2026-10-17 断联修复（第二次）：之前"回答到一半就断"的直接原因是这个看门狗把真活当成卡死。
#  - 一次工具调用（例如跑 3 分钟的测试）期间、以及模型长时间思考（首个 delta 之前）都不会产生
#    事件，idle 从 0 直接涨到分钟级；旧阈值 120s warn / 240s cancel 会在正常回合里开火。
#  - 旧的 _RUN_MAX_SEC=600 是墙钟硬杀：只要一个回合（含十几次工具调用）超过 10 分钟就整段取消，
#    与"是否卡死"无关。
# 所以：idle 阈值放宽到 5 min warn / 15 min cancel；运行时长改成"预算制"，每完成一次工具调用
# 额外续 5 分钟（上限 90 分钟），只有"很久没事件且没有工具产出"才判死。真正的复读循环仍由
# _content_looping 在回合结束时识别。
_STUCK_WARN_SEC = 300
_STUCK_CANCEL_SEC = 900
_RUN_WARN_SEC = 600
_RUN_MAX_SEC = 1800
_RUN_EXTEND_PER_TOOL_SEC = 300
_RUN_MAX_CAP_SEC = 5400
_MAX_EVENTS_PER_JOB = 500
_watchdog_task: asyncio.Task | None = None


class JobCancelled(Exception):
  pass


_jobs: dict[str, dict[str, Any]] = {}
_tasks: dict[str, asyncio.Task] = {}
_cancel_flags: dict[str, bool] = {}
_lock = asyncio.Lock()
_session_lanes: dict[str, asyncio.Lock] = {}
_idempotency: dict[str, tuple[str, int]] = {}
_IDEMPOTENCY_TTL_SEC = 120




def _new_job_id() -> str:
  return f"job_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"


def _apply_event_to_assistant(assistant: dict[str, Any], event: dict[str, Any]) -> None:
  et = event.get("type")
  if et == "content":
    assistant["content"] = (assistant.get("content") or "") + (event.get("delta") or "")
  elif et == "reasoning":
    assistant["reasoning_content"] = (assistant.get("reasoning_content") or "") + (event.get("delta") or "")
  elif et == "tool_call":
    tool_calls = assistant.setdefault("tool_calls", [])
    tid = event.get("id", "")
    if not any(tc.get("id") == tid for tc in tool_calls):
      tool_calls.append({
        "id": tid,
        "type": "function",
        "function": {"name": event.get("name", ""), "arguments": event.get("arguments", "")},
      })
  elif et == "tool_result":
    results = assistant.setdefault("tool_results", {})
    results[event.get("id", "")] = event.get("result")
  elif et == "error":
    err_text = str(event.get("error") or "")
    prev = assistant.get("content") or ""
    if prev.strip():
      # 2026-08-27: 保留已生成部分内容并标记中断（不再用错误文本覆盖）
      assistant["interrupted"] = True
      assistant["partial_error"] = err_text
    else:
      assistant["content"] = err_text


def _prune_old_jobs() -> None:
  if len(_jobs) <= _MAX_JOBS:
    return
  done = [
    (jid, j.get("updatedAt") or 0)
    for jid, j in _jobs.items()
    if j.get("status") in ("done", "error", "cancelled")
  ]
  done.sort(key=lambda x: x[1])
  for jid, _ in done[: max(0, len(_jobs) - _MAX_JOBS)]:
    if _jobs.get(jid, {}).get("status") == "running":
      continue
    _jobs.pop(jid, None)
    _cancel_flags.pop(jid, None)


async def start_chat_job(
  session_id: str,
  body: dict[str, Any],
  params: Params,
  *,
  get_state_reader: Callable,
  get_tool_handlers: Callable,
  tools: list[dict[str, Any]] | None,
  max_tool_rounds: int,
  config: Any,
  session_log_path: str | None = None,
) -> str:
  idem = str(body.get("idempotencyKey") or body.get("idempotency_key") or "").strip()
  if idem and session_id:
    cache_key = f"{session_id}:{idem}"
    now = int(time.time())
    async with _lock:
      expired = [k for k, v in _idempotency.items() if v[1] < now]
      for k in expired:
        _idempotency.pop(k, None)
      cached = _idempotency.get(cache_key)
      if cached:
        job_id, expires = cached
        if expires >= now and job_id in _jobs:
          return job_id

  job_id = _new_job_id()
  now = int(time.time())
  job = {
    "id": job_id,
    "sessionId": session_id or "",
    "status": "running",
    "events": [],
    "eventSeq": 0,
    "assistant": {
      "role": "assistant",
      "content": "",
      "reasoning_content": "",
      "tool_calls": [],
      "tool_results": {},
    },
    "createdAt": now,
    "updatedAt": now,
    "error": None,
    "resolvedModel": None,
    "runId": job_id,
    "lastEventAt": now,
    "toolCallsCompleted": 0,
    "queueMode": str(body.get("queueMode") or body.get("queue_mode") or ""),
  }
  _cancel_flags[job_id] = False
  async with _lock:
    _jobs[job_id] = job
    _prune_old_jobs()
    if idem and session_id:
      _idempotency[f"{session_id}:{idem}"] = (job_id, int(time.time()) + _IDEMPOTENCY_TTL_SEC)

  async def emit(event: dict[str, Any]) -> None:
    if _cancel_flags.get(job_id):
      raise JobCancelled()
    async with _lock:
      j = _jobs.get(job_id)
      if not j or j["status"] == "cancelled":
        raise JobCancelled()
      j["eventSeq"] += 1
      event = {**event, "_seq": j["eventSeq"]}
      j["events"].append(event)
      if len(j["events"]) > _MAX_EVENTS_PER_JOB:
        j["events"] = j["events"][-_MAX_EVENTS_PER_JOB:]
      j["updatedAt"] = int(time.time())
      j["lastEventAt"] = int(time.time())
      if event.get("type") in ("tool_result", "tool_error"):
        # 2026-10-17: 一次完成的工具调用=真实进展，给看门狗续预算（见 run_budget_sec）
        j["toolCallsCompleted"] = int(j.get("toolCallsCompleted") or 0) + 1
      _apply_event_to_assistant(j["assistant"], event)
    try:
      from ai.core.sync.hub import notify_chat_event
      await notify_chat_event(job_id, job.get("sessionId") or "", event, j)
    except Exception:
      pass

  async def _run() -> None:
    lane_key = session_id or "__global__"
    lane = _session_lanes.setdefault(lane_key, asyncio.Lock())
    async with lane:
      run_body = {**body, "_config": config, "_job_id": job_id}
      try:
        await emit({
          "type": "lifecycle",
          "phase": "start",
          "runId": job_id,
          "jobId": job_id,
          "sessionId": session_id or "",
        })
        result = await run_chat_with_agents(
          run_body,
          params,
          emit,
          get_state_reader=get_state_reader,
          get_tool_handlers=get_tool_handlers,
          tools=tools,
          max_tool_rounds=max_tool_rounds,
          is_cancelled=lambda: bool(_cancel_flags.get(job_id)),
          session_log_path=session_log_path,
        )
        async with _lock:
          j = _jobs.get(job_id)
          if not j or j["status"] == "cancelled":
            return
          if result.get("ok") is False:
            j["status"] = "error"
            j["error"] = str(result.get("error") or "Chat failed")
          else:
            j["status"] = "done"
            # 2026-08-27: 结束标志——前端据此判定消息完整（无标志=未完成，提供「继续生成」）
            # 空输出（模型返回空/无工具）不算完成——保持无标志，前端判未完成可继续
            if (j["assistant"].get("content") or j["assistant"].get("tool_calls")) and not _content_truncated(j["assistant"].get("content", "")) and not _content_looping(j["assistant"].get("content", "")):
              # 2026-08-28: 内容截断（未闭合代码块/半句结尾）→ 不打 finished → 前端判未完成可继续
              j["assistant"]["finished"] = True
          j["resolvedModel"] = result.get("resolvedModel")
          j["updatedAt"] = int(time.time())
        try:
          from ai.core.sync.hub import notify_chat_status
          j = _jobs.get(job_id)
          if j:
            await notify_chat_status(job_id, j.get("sessionId") or "", j)
        except Exception:
          pass
      except (JobCancelled, ChatCancelled):
        async with _lock:
          j = _jobs.get(job_id)
          if j and j["status"] != "cancelled":
            j["status"] = "cancelled"
            j["updatedAt"] = int(time.time())
        try:
          from ai.core.sync.hub import notify_chat_status
          j = _jobs.get(job_id)
          if j:
            await notify_chat_status(job_id, j.get("sessionId") or "", j)
        except Exception:
          pass
      except Exception as e:
        try:
          await emit({"type": "error", "error": str(e)})
        except Exception:
          pass
        async with _lock:
          j = _jobs.get(job_id)
          if j:
            j["status"] = "error"
            j["error"] = str(e)
            j["updatedAt"] = int(time.time())
        try:
          from ai.core.sync.hub import notify_chat_status
          j = _jobs.get(job_id)
          if j:
            await notify_chat_status(job_id, j.get("sessionId") or "", j)
        except Exception:
          pass
      finally:
        _tasks.pop(job_id, None)
        try:
          await emit({
            "type": "lifecycle",
            "phase": "end",
            "runId": job_id,
            "jobId": job_id,
            "sessionId": session_id or "",
          })
        except Exception:
          pass
        try:
          from ai.core.chat.command_queue import drain_session_queue

          async def _start_queued(queued_body: dict[str, Any]) -> str:
            prep_tools = tools
            prep_rounds = max_tool_rounds
            return await start_chat_job(
              session_id,
              queued_body,
              params,
              get_state_reader=get_state_reader,
              get_tool_handlers=get_tool_handlers,
              tools=prep_tools,
              max_tool_rounds=prep_rounds,
              config=config,
              session_log_path=session_log_path,
            )

          await drain_session_queue(session_id, _start_queued)
        except Exception:
          pass

  _tasks[job_id] = asyncio.create_task(_run())
  try:
    from ai.core.sync.hub import notify_chat_status
    j = _jobs.get(job_id)
    if j:
      await notify_chat_status(job_id, session_id or "", j)
  except Exception:
    pass
  return job_id


def get_job(job_id: str, since: int = 0) -> dict[str, Any] | None:
  job = _jobs.get(job_id)
  if not job:
    return None
  now = int(time.time())
  if job["status"] != "running" and (now - (job.get("updatedAt") or now)) > _JOB_TTL_SEC:
    _jobs.pop(job_id, None)
    _cancel_flags.pop(job_id, None)
    return None
  events = [e for e in job["events"] if int(e.get("_seq") or 0) > since]
  return {
    "ok": True,
    "id": job_id,
    "status": job["status"],
    "sessionId": job["sessionId"],
    "events": events,
    "assistant": job["assistant"],
    "error": job.get("error"),
    "resolvedModel": job.get("resolvedModel"),
    "updatedAt": job["updatedAt"],
    "nextSince": job["eventSeq"],
    "runId": job_id,
    "lastEventAt": job.get("lastEventAt"),
    "toolCallsCompleted": job.get("toolCallsCompleted"),
  }


async def wait_for_job(job_id: str, timeout_ms: int = 60000) -> dict[str, Any] | None:
  deadline = time.time() + max(0, timeout_ms) / 1000.0
  while time.time() < deadline:
    snap = get_job(job_id)
    if not snap:
      return None
    if snap.get("status") in ("done", "error", "cancelled"):
      return snap
    await asyncio.sleep(0.2)
  return get_job(job_id)


async def cancel_jobs_for_session(session_id: str) -> int:
  cancelled = 0
  for jid, j in list(_jobs.items()):
    if j.get("status") != "running":
      continue
    if session_id and j.get("sessionId") != session_id:
      continue
    if await cancel_job(jid):
      cancelled += 1
  return cancelled


def run_budget_sec(job: dict[str, Any] | None) -> int:
  """Wall-clock budget for one job, extended by every tool the job actually completed.

  A turn that keeps returning tool results is making progress no matter how long it takes
  (test suites, builds, model downloads all live in single tool calls). Only a job that
  burns time without completing anything stays inside the base budget.
  """
  if not job:
    return _RUN_MAX_SEC
  done = int(job.get("toolCallsCompleted") or 0)
  return min(_RUN_MAX_CAP_SEC, _RUN_MAX_SEC + _RUN_EXTEND_PER_TOOL_SEC * done)


def mark_tool_inflight(job_id: str, delta: int) -> None:
  """Track how many tool bodies are currently executing for a job.

  While a tool runs, the job emits no chat events (tool_call ... tool_result), so
  `lastEventAt` stops advancing even though real work is happening. Without this
  counter a legitimate multi-minute `run_shell_command` looks identical to a hung
  job and the stuck watchdog would cancel the answer mid-flight.
  """
  if not job_id or not delta:
    return
  j = _jobs.get(job_id)
  if not j:
    return
  j["inflightTools"] = max(0, int(j.get("inflightTools") or 0) + delta)
  j["lastEventAt"] = int(time.time())


def _scan_stuck_jobs() -> list[dict[str, Any]]:
  now = int(time.time())
  stuck: list[dict[str, Any]] = []
  for jid, j in _jobs.items():
    if j.get("status") != "running":
      continue
    if int(j.get("inflightTools") or 0) > 0:
      # A tool is actually executing (possibly a multi-minute test run). That is
      # forward progress, not a stall: the tool call itself emits no events until
      # it returns, so idle grows while work is genuinely happening. The pipeline
      # already bounds each tool with its own timeout.
      continue
    last = int(j.get("lastEventAt") or j.get("updatedAt") or 0)
    if now - last >= _STUCK_WARN_SEC:
      stuck.append({
        "jobId": jid,
        "sessionId": j.get("sessionId") or "",
        "idleSec": now - last,
        "runId": jid,
      })
  return stuck


def _scan_over_budget_jobs() -> list[dict[str, Any]]:
  """Running jobs that burned their wall-clock budget.

  Idle-gated scanning cannot see a job that keeps emitting events (the streamed-loop case), so
  the run-time guard needs its own pass. Tools still in flight are productive by definition and
  are left alone.
  """
  now = int(time.time())
  over: list[dict[str, Any]] = []
  for jid, j in _jobs.items():
    if j.get("status") != "running":
      continue
    if int(j.get("inflightTools") or 0) > 0:
      continue
    last = int(j.get("lastEventAt") or j.get("updatedAt") or 0)
    run_sec = now - int(j.get("createdAt") or last or now)
    if run_sec >= run_budget_sec(j):
      over.append({
        "jobId": jid,
        "sessionId": j.get("sessionId") or "",
        "runSec": run_sec,
      })
  return over


async def stuck_job_watchdog_loop() -> None:
  from openpilot.common.swaglog import cloudlog
  warned: set[str] = set()
  run_warned: set[str] = set()
  cancelled: set[str] = set()
  while True:
    await asyncio.sleep(30)
    now = int(time.time())
    stuck_items = _scan_stuck_jobs()
    seen = {i["jobId"] for i in stuck_items}
    # 2026-10-17: 事件不断的复读循环 idle≈0，永远不进 stuck 扫描——单独补一趟"超预算"扫描。
    items = stuck_items + [i for i in _scan_over_budget_jobs() if i["jobId"] not in seen]
    for item in items:
      try:
        jid = item["jobId"]
        idle = int(item.get("idleSec") or 0)
        j = _jobs.get(jid)
        if j and j.get("status") != "running":
          warned.discard(jid)
          run_warned.discard(jid)
          cancelled.discard(jid)
          continue
        if jid not in warned:
          warned.add(jid)
          cloudlog.warning(
            f"aid: stuck chat job {jid} session={item['sessionId']} idle={idle}s"
          )
          try:
            from ai.core.sync.hub import notify_lifecycle
            await notify_lifecycle(jid, item["sessionId"], "stuck", item)
          except Exception:
            pass
        # 2026-09-01 运行时长兜底：持续输出型循环（复读/变体重复）事件不断、idle≈0——
        # 用 createdAt（创建时间，循环期间不更新）判定总运行时长，超限强制取消
        run_sec = now - int(j.get("createdAt") or j.get("updatedAt") or now)
        budget = run_budget_sec(j)
        if jid not in run_warned and run_sec >= _RUN_WARN_SEC:
          run_warned.add(jid)
          cloudlog.warning(f"aid: long-running chat job {jid} session={item['sessionId']} run={run_sec}s budget={budget}s (loop?)")
          try:
            from ai.core.sync.hub import notify_lifecycle
            await notify_lifecycle(jid, item["sessionId"], "run_timeout_warn", {**item, "runSec": run_sec})
          except Exception:
            pass
        # 2026-10-17: 预算制——只有"跑了很久且没有任何工具产出"才判死；有产出的回合按
        # 每完成一次工具调用 +5 min 续期（run_budget_sec），长任务不会被腰斩。
        if jid not in cancelled and run_sec >= budget:
          cancelled.add(jid)
          cloudlog.warning(f"aid: auto-cancelling long-running job {jid} session={item['sessionId']} run={run_sec}s budget={budget}s")
          try:
            await cancel_job(jid)
            from ai.core.sync.hub import notify_lifecycle
            await notify_lifecycle(jid, item["sessionId"], "run_timeout", {**item, "runSec": run_sec})
          except Exception:
            pass
        # 2026-08-29 自动取消：警告后仍卡 idle≥_STUCK_CANCEL_SEC → cancel + 通知前端
        if jid not in cancelled and idle >= _STUCK_CANCEL_SEC:
          cancelled.add(jid)
          cloudlog.warning(
            f"aid: auto-cancelling stuck job {jid} session={item['sessionId']} idle={idle}s"
          )
          try:
            await cancel_job(jid)
            from ai.core.sync.hub import notify_lifecycle
            await notify_lifecycle(jid, item["sessionId"], "stuck_cancelled", item)
          except Exception:
            pass


      except Exception as e:
        # Never let one bad iteration kill the watchdog for the rest of the process.
        cloudlog.warning(f"aid: stuck watchdog iteration failed: {e}")
def ensure_stuck_watchdog() -> None:
  global _watchdog_task
  if _watchdog_task and not _watchdog_task.done():
    return
  _watchdog_task = asyncio.create_task(stuck_job_watchdog_loop())


def list_active_jobs(session_id: str | None = None) -> list[dict[str, Any]]:
  out = []
  for j in _jobs.values():
    if j.get("status") != "running":
      continue
    if session_id and j.get("sessionId") != session_id:
      continue
    out.append({
      "id": j["id"],
      "sessionId": j.get("sessionId") or "",
      "updatedAt": j.get("updatedAt") or 0,
    })
  out.sort(key=lambda x: x["updatedAt"], reverse=True)
  return out


async def cancel_job(job_id: str) -> bool:
  job = _jobs.get(job_id)
  if not job:
    return False
  _cancel_flags[job_id] = True
  task = _tasks.get(job_id)
  if task and not task.done():
    task.cancel()
  async with _lock:
    j = _jobs.get(job_id)
    if j:
      j["status"] = "cancelled"
      j["updatedAt"] = int(time.time())
  try:
    from ai.core.sync.hub import notify_chat_status
    j = _jobs.get(job_id)
    if j:
      await notify_chat_status(job_id, j.get("sessionId") or "", j)
  except Exception:
    pass
  return True
