"""REST/ACP route setup for the AI OP assistant P0 harness.

Routes are independent from the production server to avoid openpilot/cereal
import dependencies during local development and testing.

Also provides frontend-compatible fallbacks for the existing OP 助手 web UI
so the page can boot and chat in local-dev mode.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from ai.audit.log import AuditLog
from ai.core.agent.simple_loop import SimpleAgentLoop
from ai.core.config.schema import AIOPConfig, ConversationConfig, load_config
from ai.core.llm.client import AIConfig
from ai.core.session.manager import SessionManager
from ai.permissions.hitl import HumanInLoop
from ai.permissions.service import SandboxPolicyService
from ai.providers.offline import OfflineProvider
from ai.tools.dispatch import ToolDispatcher
from ai.tools.spill import SpillWaterfall
from ai.tools.vehicle.params import VehicleParams
from ai.tools.vehicle.schemas import build_vehicle_handlers, build_vehicle_tool_specs


def _vehicle_params_factory(cwd: str) -> VehicleParams:
  return VehicleParams(Path(cwd) / ".ai" / "vehicle")


def _make_dispatcher(cwd: str, config: AIOPConfig) -> ToolDispatcher:
  schemas = build_vehicle_tool_specs()
  handlers = build_vehicle_handlers(_vehicle_params_factory)
  sandbox = SandboxPolicyService(config)
  audit = AuditLog.for_session(cwd)
  hitl = HumanInLoop()
  return ToolDispatcher(handlers, schemas, sandbox, audit, hitl)


def _cwd_from_request(request: web.Request) -> str:
  body: dict[str, Any] = {}
  if request.can_read_body:
    try:
      body = request.query
    except Exception:
      pass
  return str(body.get("cwd") or request.query.get("cwd") or str(Path.cwd()))


def _make_offline_config() -> AIConfig:
  """Offline mock config used by local-dev Agent runs."""
  return AIConfig(provider="offline", model="offline-mock", api_key="offline")


def _make_tool_pipeline(config: AIOPConfig) -> tuple[list[dict[str, Any]], dict[str, Any]]:
  """Build schemas + handlers compatible with ai.core.agent.Agent.

  Uses the same vehicle/harness/agent tool registration as production, but
  bound to the standard StateReader. ToolPipeline will wrap sync/async handlers.
  """
  from ai.tools.agent_tools import build_tool_schemas, make_handlers

  schemas = build_tool_schemas()

  def _get_state_reader():
    from ai.selfdrive.state import StateReader
    return StateReader()

  handlers = make_handlers(get_state_reader=_get_state_reader, params=Params())
  return schemas, handlers


def _make_agent(
  cwd: str,
  config: AIOPConfig,
  body: dict[str, Any],
  emit: Callable[[dict[str, Any]], Awaitable[None]],
  session_id: str,
  get_state_reader: Callable[[], Any],
) -> "Agent":
  """Construct a production Agent instance with AgentLoop enabled by default.

  Tool schemas come from ``ai.tools.agent_tools.build_tool_schemas()`` and
  handlers are built via ``ai.tools.agent_tools.make_handlers(...)``.  This
  helper centralizes the construction seam exercised by T02 regression tests.
  """
  from ai.core.agent.agent import Agent

  # Force AgentLoop default for local-dev harness.
  body = {**body, "ai_use_agent_loop": True}

  def _get_tool_handlers() -> dict[str, Any]:
    _schemas, handlers = _make_tool_pipeline(config)
    return handlers

  agent_id = str(body.get("agent_id") or body.get("agentId") or "local-dev").strip() or "local-dev"
  ai_config = _make_offline_config()
  tool_schemas, _ = _make_tool_pipeline(config)

  return Agent(
    session_id=session_id,
    agent_id=agent_id,
    params=Params(),
    config=ai_config,
    body=body,
    emit=emit,
    get_state_reader=get_state_reader,
    get_tool_handlers=_get_tool_handlers,
    tools=tool_schemas,
    max_tool_rounds=int(body.get("max_tool_rounds") or config.conversation.ai_max_turns or 16),
    tool_timeout=float(body.get("tool_timeout") or config.conversation.ai_tool_timeout or 60.0),
    stream_timeout=float(body.get("stream_timeout") or config.conversation.ai_stream_timeout or 120.0),
    ai_use_agent_loop=True,
  )


async def _run_with_agent(
  cwd: str,
  config: AIOPConfig,
  body: dict[str, Any],
  prompt: str,
  session_id: str,
) -> dict[str, Any]:
  """Run one chat turn through the production Agent (AgentLoop by default).

  Falls back to SimpleAgentLoop if Agent construction/execution fails so the
  local-dev server stays usable even when production dependencies are missing.
  """
  from ai.core.agent.registry import agent_registry

  if prompt and not body.get("messages"):
    body["messages"] = [{"role": "user", "content": prompt}]

  events: list[dict[str, Any]] = []

  async def _emit(event: dict[str, Any]) -> None:
    events.append(event)

  def _get_state_reader():
    from ai.selfdrive.state import StateReader
    return StateReader()

  agent = _make_agent(cwd, config, body, _emit, session_id, _get_state_reader)
  job_id = str(body.get("_job_id") or body.get("jobId") or "").strip()

  async def _cancel() -> bool:
    try:
      agent.cancel()
      return True
    except Exception:
      return False

  entry = agent_registry.resume(
    session_id,
    agent.agent_id,
    job_id=job_id,
    meta={"mode": str(body.get("mode") or body.get("chatMode") or "local-dev")},
    cancel_fn=_cancel,
  )
  try:
    result = await agent.run()
    return {"ok": True, "agent": result, "events": events}
  finally:
    status = "done"
    if getattr(agent, "state", None) is not None and agent.state.is_cancelled():
      status = "cancelled"
    elif entry is not None:
      agent_registry.mark_done(session_id, status)


async def _run_simple_loop(
  cwd: str,
  config: AIOPConfig,
  body: dict[str, Any],
  prompt: str,
  session_id: str,
) -> dict[str, Any]:
  """Original P0 fallback loop (preserved for resilience)."""
  sessions = SessionManager(cwd)
  session = sessions.get_or_create(session_id, cwd=cwd)
  dispatcher = _make_dispatcher(cwd, config)
  spill = SpillWaterfall(cwd)
  provider = OfflineProvider()
  loop = SimpleAgentLoop(session, sessions.storage, dispatcher, provider, config, spill=spill)
  result = await loop.run(prompt)
  return {"ok": True, "fallback": "simple_loop", "result": result}


def _extract_prompt(messages: list[dict[str, Any]]) -> str:
  """Extract the latest user text prompt from an OpenAI-style messages list."""
  for m in reversed(messages):
    if m.get("role") == "user":
      content = m.get("content")
      if isinstance(content, str):
        return content
      if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if p.get("type") == "text")
  return ""


async def _run_chat_local_dev(
  cwd: str,
  config: AIOPConfig,
  body: dict[str, Any],
  prompt: str,
  session_id: str,
) -> dict[str, Any]:
  """Try production Agent first, fallback to SimpleAgentLoop on failure."""
  try:
    return await _run_with_agent(cwd, config, body, prompt, session_id)
  except Exception as e:
    # Log and fallback so local-dev never hard-fails when Agent deps are unavailable.
    import logging
    logging.getLogger("ai.op_routes").warning(f"Agent run failed, falling back to SimpleAgentLoop: {e}")
    return await _run_simple_loop(cwd, config, body, prompt, session_id)


async def _extract_reply(result: Any) -> str:
  """Extract assistant text from an Agent or fallback result."""
  if not isinstance(result, dict):
    return str(result)
  if result.get("fallback"):
    fb_result = result.get("result") or {}
    if isinstance(fb_result, dict):
      return str(fb_result.get("reply", "") or fb_result.get("answer", "") or fb_result.get("content", ""))
    return str(fb_result)
  agent_result = result.get("agent") or {}
  if isinstance(agent_result, dict):
    return str(agent_result.get("reply", "") or agent_result.get("answer", "") or agent_result.get("content", ""))
  return ""


async def health(_request: web.Request) -> web.Response:
  return web.json_response({"ok": True, "service": "ai-op-assistant-enhanced"})


async def api_config_diagnose(request: web.Request) -> web.Response:
  config = request.app.get("config") or AIOPConfig()
  return web.json_response({
    "ok": True,
    "config": config.to_dict(),
    "diagnostics": {
      "agent_loop_enabled": config.conversation.ai_use_agent_loop,
      "audit_enabled": config.dev_diagnostics.enable_audit,
      "automations_enabled": config.agent_scheduler.automations_enabled,
    },
  })


async def api_config_get(request: web.Request) -> web.Response:
  config = request.app.get("config") or AIOPConfig()
  return web.json_response({
    "ok": True,
    "revision": 1,
    "config": config.to_dict(),
  })


async def api_config_post(request: web.Request) -> web.Response:
  body = await request.json()
  config = request.app.get("config") or AIOPConfig()
  raw = body.get("config") or body
  for section, values in raw.items():
    if hasattr(config, section) and isinstance(values, dict):
      current = getattr(config, section)
      for k, v in values.items():
        if hasattr(current, k):
          setattr(current, k, v)
  return web.json_response({"ok": True, "revision": 2, "config": config.to_dict()})


async def api_status(_request: web.Request) -> web.Response:
  return web.json_response({
    "ok": True,
    "service": "ai-op-assistant-enhanced",
    "mode": "local-dev",
    "driving": False,
    "state": {"enabled": False, "v_ego_m_s": 0.0, "ignition": True},
    "model": "offline-mock",
    "provider": "offline",
    "configured": True,
  })


async def api_bootstrap(request: web.Request) -> web.Response:
  lite = request.query.get("lite") == "1"
  data = {
    "ok": True,
    "service": "ai-op-assistant-enhanced",
    "mode": "local-dev",
    "config": AIOPConfig().to_dict(),
    "providers": ["offline"],
    "models": [{"id": "offline-mock", "name": "Offline Mock"}],
  }
  if not lite:
    data["agents"] = []
    data["skills"] = []
    data["tools"] = []
  return web.json_response(data)


async def api_providers(_request: web.Request) -> web.Response:
  return web.json_response({
    "ok": True,
    "providers": [
      {"id": "offline", "name": "Offline Mock", "configured": True},
    ],
  })


_JOBS: dict[str, dict[str, Any]] = {}


async def api_chat_jobs_create(request: web.Request) -> web.Response:
  body = await request.json()
  job_id = uuid.uuid4().hex
  session_id = str(body.get("session_id") or body.get("sessionId") or "").strip()
  _JOBS[job_id] = {
    "id": job_id,
    "status": "pending",
    "session_id": session_id,
    "messages": body.get("messages", []),
    "created_at": time.time(),
    "result": None,
  }
  # Execute synchronously for local-dev simplicity.
  config = AIOPConfig(conversation=ConversationConfig(ai_sandbox_mode="workspace_write"))
  cwd = "C:/Users/mouxan/AppData/Local/Temp/ai_op_job"
  prompt = _extract_prompt(_JOBS[job_id]["messages"])
  result = await _run_chat_local_dev(cwd, config, body, prompt or "help", session_id)
  _JOBS[job_id]["status"] = "completed"
  _JOBS[job_id]["result"] = result
  return web.json_response({"ok": True, "job_id": job_id, "status": "completed", "data": result})


async def api_chat_jobs_get(request: web.Request) -> web.Response:
  job_id = request.match_info.get("job_id", "")
  since = int(request.query.get("since", "0") or "0")
  job = _JOBS.get(job_id, {"status": "not_found"})
  events: list[dict[str, Any]] = []
  if job.get("status") == "completed":
    events.append({"type": "done", "data": job.get("result")})
  return web.json_response({"ok": True, "job_id": job_id, "status": job.get("status"), "events": events, "since": since})


async def api_chat_jobs_list(request: web.Request) -> web.Response:
  session_id = request.query.get("sessionId", "")
  jobs = [j for j in _JOBS.values() if not session_id or j.get("session_id") == session_id]
  return web.json_response({"ok": True, "jobs": jobs})


async def api_chat_jobs_stream(request: web.Request) -> web.Response:
  job_id = request.match_info.get("job_id", "")
  job = _JOBS.get(job_id, {"status": "not_found"})
  body = json.dumps({"ok": True, "job_id": job_id, "status": job.get("status"), "events": [{"type": "done", "data": job.get("result")}]})
  return web.Response(
    body=b"data: " + body.encode("utf-8") + b"\n\n",
    content_type="text/event-stream",
    headers={"Cache-Control": "no-cache"},
  )


async def api_write_confirm(request: web.Request) -> web.Response:
  return web.json_response({"ok": True, "confirmed": True})


async def api_chat(request: web.Request) -> web.Response:
  body = await request.json()
  config = request.app.get("config") or AIOPConfig()
  if body.get("sandbox_mode"):
    config.conversation.ai_sandbox_mode = str(body.get("sandbox_mode"))
  cwd = str(body.get("cwd") or str(Path.cwd()))
  prompt = str(body.get("prompt") or "")
  session_id = str(body.get("session_id") or "")

  result = await _run_chat_local_dev(cwd, config, body, prompt, session_id)
  return web.json_response(result)


async def api_chat_completions(request: web.Request) -> web.Response:
  """OpenAI-compatible chat completions endpoint used by the web UI."""
  body = await request.json()
  messages = body.get("messages", [])
  prompt = _extract_prompt(messages)
  session_id = str(body.get("session_id") or body.get("sessionId") or "")
  stream = bool(body.get("stream", False))

  config = request.app.get("config") or AIOPConfig()
  if body.get("sandbox_mode"):
    config.conversation.ai_sandbox_mode = str(body.get("sandbox_mode"))
  cwd = str(body.get("cwd") or str(Path.cwd()))

  result = await _run_chat_local_dev(cwd, config, body, prompt, session_id)

  text = await _extract_reply(result)
  completion_id = f"chatcmpl-{uuid.uuid4().hex}"
  response = {
    "id": completion_id,
    "object": "chat.completion",
    "created": int(time.time()),
    "model": body.get("model", "offline-mock"),
    "choices": [
      {
        "index": 0,
        "message": {"role": "assistant", "content": text},
        "finish_reason": "stop",
      }
    ],
    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
  }
  if stream:
    # Minimal SSE stream.
    async def _sse():
      chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": response["created"],
        "model": response["model"],
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}],
      }
      yield b"data: " + json.dumps(chunk, ensure_ascii=False).encode("utf-8") + b"\n\n"
      done = {"id": completion_id, "object": "chat.completion.chunk", "created": response["created"], "model": response["model"], "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
      yield b"data: " + json.dumps(done, ensure_ascii=False).encode("utf-8") + b"\n\ndata: [DONE]\n\n"
    return web.Response(body=_sse(), content_type="text/event-stream", headers={"Cache-Control": "no-cache"})
  return web.json_response(response)


async def api_session_resume(request: web.Request) -> web.Response:
  body = await request.json()
  session_id = str(body.get("session_id") or "")
  cwd = str(body.get("cwd") or str(Path.cwd()))
  sessions = SessionManager(cwd)
  session, repaired = sessions.resume(session_id)
  return web.json_response({"ok": True, "session": session.to_dict(), "repaired": repaired})


async def api_sessions(request: web.Request) -> web.Response:
  cwd = _cwd_from_request(request)
  sessions = SessionManager(cwd)
  compact = request.query.get("compact") == "1"
  contact = request.query.get("contact") == "1"
  session_id = request.query.get("session_id", "")
  if session_id:
    session = sessions.storage.load_session(session_id)
    return web.json_response({"ok": True, "sessions": [session.to_dict()] if session else []})
  if compact or contact:
    return web.json_response({"ok": True, "sessions": []})
  # Return at least a default session so the frontend has something to display.
  session = sessions.create(title="本地会话")
  return web.json_response({"ok": True, "sessions": [session.to_dict()]})


async def api_sessions_create(request: web.Request) -> web.Response:
  body = await request.json()
  cwd = _cwd_from_request(request)
  sessions = SessionManager(cwd)
  session = sessions.create(title=body.get("title", "新会话"))
  return web.json_response({"ok": True, "session": session.to_dict()})


async def api_session_log(request: web.Request) -> web.Response:
  session_id = request.match_info.get("session_id", "")
  cwd = _cwd_from_request(request)
  sessions = SessionManager(cwd)
  session = sessions.storage.load_session(session_id)
  if session is None:
    return web.json_response({"ok": False, "error": "session not found"}, status=404)
  events = sessions.storage.read_transcript(session)
  return web.json_response({"ok": True, "events": [ev.to_dict() for ev in events]})


async def api_audit_verify(request: web.Request) -> web.Response:
  cwd = str(request.query.get("cwd") or str(Path.cwd()))
  audit = AuditLog.for_session(cwd)
  ok, message = audit.verify()
  return web.json_response({"ok": ok, "message": message})


async def api_notifications(request: web.Request) -> web.Response:
  unread = request.query.get("unread")
  if request.method == "POST":
    return web.json_response({"ok": True, "cleared": True})
  return web.json_response({"ok": True, "notifications": [], "unread": 0 if unread is not None else None})


async def api_sync_ws(request: web.Request) -> web.WebSocketResponse:
  ws = web.WebSocketResponse()
  await ws.prepare(request)
  async for msg in ws:
    if msg.type == web.WSMsgType.TEXT:
      await ws.send_json({"type": "pong", "payload": msg.data})
  return ws


async def api_rag(request: web.Request) -> web.Response:
  return web.json_response({"ok": True, "docs": []})


async def api_files_content(request: web.Request) -> web.Response:
  """Read or write repo file content for the tools panel."""
  from ai.tools.file_search import read_repo_file_snippet

  if request.method == "GET":
    path = str(request.query.get("path") or "")
    if not path.strip():
      return web.json_response({"ok": False, "error": "path is required"}, status=400)
    return web.json_response(read_repo_file_snippet(path, max_chars=48000))

  if request.method == "POST":
    try:
      body = await request.json()
    except json.JSONDecodeError:
      return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
    path = str(body.get("path") or "")
    content = body.get("content")
    if not path.strip() or not isinstance(content, str):
      return web.json_response({"ok": False, "error": "path and content required"}, status=400)

    root = Path.cwd()
    target = (root / path).resolve()
    try:
      target.relative_to(root.resolve())
    except ValueError:
      return web.json_response({"ok": False, "error": "path escapes workspace"}, status=403)

    try:
      target.parent.mkdir(parents=True, exist_ok=True)
      target.write_text(content, encoding="utf-8")
      return web.json_response({"ok": True, "path": path, "bytes": len(content.encode("utf-8"))})
    except Exception as e:
      return web.json_response({"ok": False, "error": str(e)}, status=500)

  return web.json_response({"ok": False, "error": "method not allowed"}, status=405)


async def tools_panel_page(request: web.Request) -> web.Response:
  """Serve the standalone WorkBuddy-style tools panel page."""
  web_dir = Path(__file__).resolve().parent.parent / "web" / "static"
  panel_path = web_dir / "tools-panel.html"
  if panel_path.is_file():
    return web.FileResponse(panel_path)
  return web.json_response({"ok": False, "error": "tools-panel.html not found"}, status=404)


async def api_fallback(request: web.Request) -> web.Response:
  """Catch-all fallback for unimplemented production endpoints in local-dev mode."""
  path = request.path
  if path.endswith("/ws") or path.endswith("/stream"):
    return web.json_response({"ok": True, "mode": "local-dev"})
  # Provide sensible empty defaults for common read endpoints.
  if "sessions/search" in path:
    return web.json_response({"ok": True, "sessions": []})
  if "/memory" in path:
    return web.json_response({"ok": True, "memories": []})
  if "/rag" in path:
    return web.json_response({"ok": True, "docs": []})
  if "/skills" in path or "/agents" in path:
    return web.json_response({"ok": True, "items": []})
  if "/tools" in path or "/models" in path:
    return web.json_response({"ok": True, "items": []})
  if "/notifications" in path:
    return web.json_response({"ok": True, "notifications": [], "unread": 0})
  if "/feedback" in path:
    return web.json_response({"ok": True, "feedback": []})
  if "/issues" in path:
    return web.json_response({"ok": True, "issues": []})
  if "/workflows" in path:
    return web.json_response({"ok": True, "workflows": []})
  if "/goals" in path or "/plans" in path or "/todos" in path:
    return web.json_response({"ok": True, "items": []})
  if "/transcript" in path:
    return web.json_response({"ok": True, "events": []})
  if "/audit" in path:
    return web.json_response({"ok": True, "entries": []})
  if "/usage" in path:
    return web.json_response({"ok": True, "usage": {}})
  if "/mcp" in path or "/learned-skills" in path:
    return web.json_response({"ok": True, "items": []})
  if "/harness/config" in path:
    return web.json_response({"ok": True, "config": {}})
  if "/platform/" in path or "/device/" in path or "/workspace" in path:
    return web.json_response({"ok": True})
  if "/fork/" in path or "/publish" in path or "/package/" in path:
    return web.json_response({"ok": True})
  if "/onboarding/" in path:
    return web.json_response({"ok": True})
  if "/dev-assets" in path or "/dev-cache" in path:
    return web.json_response({"ok": True, "items": []})
  if "/files/" in path or "/context/" in path:
    return web.json_response({"ok": True, "items": []})
  if "/consumer/" in path:
    return web.json_response({"ok": True, "items": []})
  if "/model-hub/" in path:
    return web.json_response({"ok": True, "models": []})
  if "/scheduler" in path:
    return web.json_response({"ok": True, "tasks": []})
  if "/pc-sessions" in path:
    return web.json_response({"ok": True, "sessions": []})
  if "/canvas" in path:
    return web.json_response({"ok": True, "canvas": []})
  if "/terminal/" in path:
    return web.json_response({"ok": True, "output": ""})
  if path.startswith("/api/eps/"):
    return web.json_response({"ok": True, "mode": "local-dev", "path": path})
  if "/write/" in path or "/tune" in path:
    return web.json_response({"ok": True})
  if "/test" in path or "/test_connection" in path:
    return web.json_response({"ok": True, "reachable": True})
  return web.json_response({"ok": True, "mode": "local-dev", "path": path})


def setup_routes(app: web.Application) -> None:
  app.router.add_get("/api/ai/health", health)
  app.router.add_get("/api/ai/config", api_config_get)
  app.router.add_post("/api/ai/config", api_config_post)
  app.router.add_get("/api/ai/config/diagnose", api_config_diagnose)
  app.router.add_get("/api/ai/status", api_status)
  app.router.add_get("/api/ai/bootstrap", api_bootstrap)
  app.router.add_get("/api/ai/providers", api_providers)
  app.router.add_post("/api/ai/chat", api_chat)
  app.router.add_post("/api/ai/chat/completions", api_chat_completions)
  app.router.add_get("/api/ai/chat/jobs", api_chat_jobs_list)
  app.router.add_post("/api/ai/chat/jobs", api_chat_jobs_create)
  app.router.add_get("/api/ai/chat/jobs/{job_id}", api_chat_jobs_get)
  app.router.add_delete("/api/ai/chat/jobs/{job_id}", api_chat_jobs_get)
  app.router.add_get("/api/ai/chat/jobs/{job_id}/stream", api_chat_jobs_stream)
  app.router.add_post("/api/ai/write/confirm", api_write_confirm)
  app.router.add_get("/api/ai/sessions", api_sessions)
  app.router.add_post("/api/ai/sessions", api_sessions_create)
  app.router.add_get("/api/ai/sessions/{session_id}/log", api_session_log)
  app.router.add_post("/api/ai/session/resume", api_session_resume)
  app.router.add_get("/api/ai/audit/verify", api_audit_verify)
  app.router.add_get("/api/ai/notifications", api_notifications)
  app.router.add_post("/api/ai/notifications", api_notifications)
  app.router.add_get("/api/ai/sync/ws", api_sync_ws)
  app.router.add_get("/api/ai/rag", api_rag)
  app.router.add_post("/api/ai/rag", api_rag)
  app.router.add_get("/api/ai/files/content", api_files_content)
  app.router.add_post("/api/ai/files/content", api_files_content)
  app.router.add_get("/tools-panel", tools_panel_page)

  # P2 skill lifecycle routes.
  from ai.server.handlers import skills as skills_lifecycle_handlers
  app.router.add_post("/api/ai/skills/{id}/dispose", skills_lifecycle_handlers.api_skill_dispose)
  app.router.add_get("/api/ai/skills/{id}/diagnose", skills_lifecycle_handlers.api_skill_diagnose)
  app.router.add_post("/api/ai/skills/diagnose-all", skills_lifecycle_handlers.api_skill_diagnose_all)
  app.router.add_post("/api/ai/skills/session/register", skills_lifecycle_handlers.api_skill_session_register)

  # Catch-all fallback: must be last. Handles all unimplemented production endpoints.
  app.router.add_route("*", "/api/ai/{tail:.*}", api_fallback)
