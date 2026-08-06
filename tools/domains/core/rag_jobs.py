"""Background RAG reindex / wiki ingest jobs."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog

from ai.core.llm.embedding import EmbeddingConfig, embed_texts_with_failover

_JOBS: dict[str, dict[str, Any]] = {}
_CURRENT: str | None = None


def job_status(job_id: str | None = None) -> dict[str, Any]:
  if job_id:
    job = _JOBS.get(job_id)
    if not job:
      return {"ok": False, "error": "job not found"}
    return {"ok": True, "job": dict(job)}
  active = _JOBS.get(_CURRENT) if _CURRENT else None
  return {
    "ok": True,
    "currentJobId": _CURRENT,
    "job": dict(active) if active else None,
    "jobs": [dict(j) for j in _JOBS.values()][-5:],
  }


async def _run_job(
  job_id: str,
  params: Params,
  operation: str,
  *,
  wiki_options: dict[str, Any] | None = None,
  chain_reindex: bool = True,
) -> None:
  global _CURRENT
  job = _JOBS[job_id]
  try:
    job["status"] = "running"
    job["startedAt"] = int(time.time())
    if operation == "wiki_ingest":
      from ai.fork.wiki_ingest import ingest_wikis_for_current_fork

      opts = wiki_options or {}
      result = await asyncio.get_running_loop().run_in_executor(
        None,
        lambda: ingest_wikis_for_current_fork(
          force=bool(opts.get("force")),
          all_registered=bool(opts.get("all_registered")),
          max_files_per_repo=int(opts.get("max_files_per_repo", 35) or 35),
        ),
      )
      job["wiki"] = result
      if chain_reindex:
        operation = "reindex"
    if operation == "reindex":
      from ai.tools.domains.core.rag_store import reindex_all

      result = await reindex_all(params)
      job["reindex"] = result
    job["status"] = "done"
    job["finishedAt"] = int(time.time())
  except Exception as e:
    cloudlog.error(f"aid: rag job {job_id} failed: {e}")
    job["status"] = "error"
    job["error"] = str(e)
    job["finishedAt"] = int(time.time())
  finally:
    if _CURRENT == job_id:
      _CURRENT = None


async def start_rag_job(
  params: Params,
  embed_cfg: EmbeddingConfig | None,
  *,
  operation: str = "reindex",
  wiki_options: dict[str, Any] | None = None,
  chain_reindex: bool = True,
) -> dict[str, Any]:
  del embed_cfg
  global _CURRENT
  if _CURRENT and _JOBS.get(_CURRENT, {}).get("status") == "running":
    return {"ok": False, "error": "已有任务在运行", "job": job_status(_CURRENT)}
  job_id = f"rag_{uuid.uuid4().hex[:10]}"
  _JOBS[job_id] = {
    "id": job_id,
    "operation": operation,
    "status": "queued",
    "createdAt": int(time.time()),
  }
  _CURRENT = job_id
  asyncio.create_task(_run_job(job_id, params, operation, wiki_options=wiki_options, chain_reindex=chain_reindex))
  return {"ok": True, "jobId": job_id, "job": job_status(job_id)}
