"""Background RAG maintenance jobs — wiki ingest & reindex without blocking HTTP."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog

_lock = asyncio.Lock()
_job: dict[str, Any] | None = None
_task: asyncio.Task | None = None


def _public_job() -> dict[str, Any]:
  if not _job:
    return {"ok": True, "running": False}
  return {
    "ok": True,
    "running": _job.get("status") == "running",
    "id": _job.get("id"),
    "status": _job.get("status"),
    "phase": _job.get("phase"),
    "operation": _job.get("operation"),
    "started_at": _job.get("started_at"),
    "updated_at": _job.get("updated_at"),
    "result": _job.get("result"),
    "error": _job.get("error"),
  }


def is_running() -> bool:
  return bool(_job and _job.get("status") == "running")


def _touch(**fields: Any) -> None:
  global _job
  if _job is None:
    return
  _job.update(fields)
  _job["updated_at"] = time.time()


async def start_rag_job(
  params: Params,
  embed_cfg: Any,
  *,
  operation: str,
  wiki_options: dict[str, Any] | None = None,
  chain_reindex: bool = False,
) -> dict[str, Any]:
  """Start wiki_ingest and/or reindex in the background."""
  global _job, _task

  async with _lock:
    if is_running():
      return {
        "ok": False,
        "error": "知识库任务进行中，请稍后再试",
        "job": _public_job(),
      }

    job_id = f"rag_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    _job = {
      "id": job_id,
      "status": "running",
      "phase": "starting",
      "operation": operation,
      "started_at": time.time(),
      "updated_at": time.time(),
      "result": None,
      "error": None,
    }
    _task = asyncio.create_task(
      _run_job(params, embed_cfg, operation, wiki_options or {}, chain_reindex)
    )

  return {"ok": True, "started": True, "job_id": job_id, "job": _public_job()}


async def _run_job(
  params: Params,
  embed_cfg: Any,
  operation: str,
  wiki_options: dict[str, Any],
  chain_reindex: bool,
) -> None:
  from ai.tools.rag_store import reindex_all

  loop = asyncio.get_event_loop()
  try:
    wiki_res: dict[str, Any] | None = None

    if operation in ("wiki_ingest", "sync_wiki"):
      _touch(phase="wiki_ingest")
      from ai.fork.wiki_ingest import ingest_wikis_for_current_fork

      max_files = int(wiki_options.get("max_files_per_repo", 35) or 35)
      force = bool(wiki_options.get("force", False))
      include_all = bool(wiki_options.get("all_registered", False))

      def sync_wiki() -> dict[str, Any]:
        return ingest_wikis_for_current_fork(
          params,
          max_files_per_repo=max_files,
          force=force,
          include_all_registered=include_all,
        )

      wiki_res = await loop.run_in_executor(None, sync_wiki)
      _touch(phase="wiki_done", result={"wiki": wiki_res})

      should_reindex = chain_reindex or int(wiki_res.get("indexed") or 0) > 0
      if not should_reindex:
        _touch(status="done", phase="done")
        cloudlog.info(f"aid: rag job wiki indexed={wiki_res.get('indexed')}")
        return

      operation = "reindex"

    if operation == "reindex":
      if not embed_cfg.is_configured:
        _touch(status="error", error="Embedding 未配置，无法建立向量索引")
        return
      _touch(phase="reindex")
      res = await reindex_all(params, embed_cfg)
      merged = {"reindex": res}
      if wiki_res is not None:
        merged["wiki"] = wiki_res
      _touch(status="done", phase="done", result=merged)
      cloudlog.info(
        f"aid: rag job reindex indexed={res.get('indexed')}/{res.get('total')}"
      )
      return

    _touch(status="error", error=f"unknown operation: {operation}")
  except Exception as e:
    cloudlog.exception("aid: rag job failed")
    _touch(status="error", error=str(e))
  finally:
    _touch(updated_at=time.time())


def job_status() -> dict[str, Any]:
  return _public_job()
