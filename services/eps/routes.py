"""aiohttp routes for EPS telescope / 8965B4512000 patch panel.

Design constraints (keep the brick risk as low as possible):

- All probe operations are read-only but stop manager/pandad; they run in a
  background thread pool and are polled by the UI.
- The destructive ``patch`` / ``restore`` writers are **never** exposed as HTTP
  endpoints. The panel only shows the prepared command and asks the operator to
  run it manually in a foreground interactive SSH TTY with upper-case YES.
- Offroad + confirm gates are enforced both on the backend and in the UI.
- Telescope classification must be ``verified_variant`` or ``already_patched``
  before eps_patch_probe is accepted.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from openpilot.common.swaglog import cloudlog

from ai.server.deps import get_state_reader, json_response, params
from ai.system.admin import is_admin_mode
from ai.system.safety import is_action_allowed
from ai.tools.domains.secoc.eps_patch_tools import (
  eps_patch_diagnose as _eps_patch_diagnose,
  eps_patch_prepare_patch as _eps_patch_prepare_patch,
  eps_patch_prepare_restore as _eps_patch_prepare_restore,
  eps_patch_probe as _eps_patch_probe,
  eps_patch_status as _eps_patch_status,
  eps_telescope_classify as _eps_telescope_classify,
  eps_telescope_probe as _eps_telescope_probe,
  eps_telescope_status as _eps_telescope_status,
)
from ai.tools.domains.platform.audit_store import record_audit


_PARAMS = params()


def _json(data: dict, *, status: int = 200) -> web.Response:
  return web.json_response(data, status=status)


# ---------------------------------------------------------------------------
# In-memory job registry. Jobs hold stdout/stderr lines streamed from the
# underlying subprocess. All writer operations are refused at the API layer.
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _Job:
  job_id: str
  kind: str  # "telescope_probe" | "patch_probe"
  command: list[str]
  cwd: Path
  status: str  # "pending" | "running" | "done" | "error" | "cancelled"
  returncode: int | None = None
  lines: list[dict[str, str]] = dataclasses.field(default_factory=list)
  error: str = ""
  cancelled: bool = False
  _proc: subprocess.Popen[str] | None = None
  _lock: threading.RLock = dataclasses.field(default_factory=threading.RLock)

  def to_dict(self) -> dict[str, Any]:
    with self._lock:
      return {
        "job_id": self.job_id,
        "kind": self.kind,
        "command": self.command,
        "status": self.status,
        "returncode": self.returncode,
        "lines": list(self.lines),
        "error": self.error,
        "cancelled": self.cancelled,
      }


_JOBS: dict[str, _Job] = {}
_JOBS_LOCK = threading.Lock()


def _allowed(action: str) -> tuple[bool, str]:
  reader = get_state_reader()
  if reader is None:
    return False, "vehicle state reader unavailable"
  state = reader.update(timeout=0)
  return is_action_allowed(action, state, admin=is_admin_mode(_PARAMS))


def _offroad_reason() -> str:
  reader = get_state_reader()
  if reader is None:
    return "state reader unavailable"
  state = reader.update(timeout=0)
  if getattr(state, "started", False) and not getattr(state, "force_offroad", False):
    return "EPS 操作仅能在 offroad 下进行。"
  return ""


def _audit(action: str, result: dict[str, Any]) -> None:
  try:
    record_audit(
      action=action,
      tool=action,
      detail={
        "ok": result.get("ok"),
        "error": result.get("error"),
        "job_id": result.get("job_id"),
        "kind": result.get("kind"),
      },
      ok=bool(result.get("ok")),
    )
  except Exception:
    pass


def _stream_worker(job: _Job) -> None:
  """Run subprocess and append stdout/stderr lines to the job record."""
  try:
    with job._lock:
      if job.cancelled:
        job.status = "cancelled"
        return
      job.status = "running"
    proc = subprocess.Popen(
      job.command,
      stdout=subprocess.PIPE,
      stderr=subprocess.STDOUT,
      text=True,
      cwd=str(job.cwd),
      bufsize=1,
    )
    with job._lock:
      job._proc = proc
    for line in proc.stdout or []:
      line = line.rstrip("\n")
      with job._lock:
        job.lines.append({"t": time.monotonic(), "line": line})
        if job.cancelled:
          proc.terminate()
          break
    proc.wait(timeout=30)
    with job._lock:
      job.returncode = proc.returncode
      job.status = "done" if proc.returncode == 0 else "error"
      job._proc = None
  except Exception as exc:
    cloudlog.exception("eps job worker failed")
    with job._lock:
      job.error = str(exc)
      job.status = "error"
      job._proc = None


def _start_job(kind: str, command: list[str], cwd: Path) -> _Job:
  job_id = uuid.uuid4().hex[:12]
  job = _Job(job_id=job_id, kind=kind, command=command, cwd=cwd)
  with _JOBS_LOCK:
    _JOBS[job_id] = job
  thread = threading.Thread(target=_stream_worker, args=(job,), daemon=True)
  thread.start()
  return job


def _get_job(job_id: str) -> _Job | None:
  with _JOBS_LOCK:
    return _JOBS.get(job_id)


# ---------------------------------------------------------------------------
# Helpers to call eps_patch_tools synchronously in executor.
# ---------------------------------------------------------------------------


def _run_sync(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
  loop = asyncio.get_running_loop()
  return loop.run_in_executor(None, lambda: fn(*args, **kwargs))


# ---------------------------------------------------------------------------
# HTTP handlers.
# ---------------------------------------------------------------------------


async def api_eps_status(_request: web.Request) -> web.Response:
  status = await _run_sync(_eps_patch_status)
  return _json(status)


async def api_eps_telescope_status(_request: web.Request) -> web.Response:
  status = await _run_sync(_eps_telescope_status)
  return _json(status)


async def api_eps_telescope_classify(_request: web.Request) -> web.Response:
  result = await _run_sync(_eps_telescope_classify)
  return _json(result)


async def api_eps_diagnose(_request: web.Request) -> web.Response:
  result = await _run_sync(_eps_patch_diagnose)
  return _json(result)


async def api_eps_prepare_patch(_request: web.Request) -> web.Response:
  result = await _run_sync(_eps_patch_prepare_patch, get_state_reader=get_state_reader)
  return _json(result)


async def api_eps_prepare_restore(_request: web.Request) -> web.Response:
  result = await _run_sync(_eps_patch_prepare_restore, get_state_reader=get_state_reader)
  return _json(result)


async def api_eps_telescope_probe(request: web.Request) -> web.Response:
  allowed, reason = _allowed("shell")
  if not allowed:
    return _json({"ok": False, "error": reason}, status=403)

  offroad = _offroad_reason()
  if offroad:
    return _json({"ok": False, "error": offroad}, status=403)

  try:
    body = await request.json()
  except Exception:
    body = {}

  if not body.get("confirm"):
    return _json({
      "ok": True,
      "needs_confirmation": True,
      "hint": "将停止 manager/pandad，对 EPS 执行只读分层探测（eps-telescope）。确认后继续。",
    })

  serial = str(body.get("serial") or "")
  addr = str(body.get("addr") or "")
  depth = str(body.get("depth") or "shellcode")

  # Resolve command. We run the vendor probe.py directly via subprocess so the
  # UI can stream stdout. This mirrors the chat tool behaviour but adds polling.
  from ai.tools.domains.secoc.eps_patch_tools import EPS_TELESCOPE_SCRIPT, _python, _telescope_artifact_root

  script = EPS_TELESCOPE_SCRIPT if EPS_TELESCOPE_SCRIPT.exists() else Path("/data/eps-telescope/app/probe.py")
  out_dir = str(_telescope_artifact_root())
  cmd = [_python(), str(script), "--depth", depth, "--artifacts-dir", out_dir]
  if serial:
    cmd += ["--serial", serial]
  if addr:
    cmd += ["--addr", addr]
  if body.get("no_egg_scan"):
    cmd += ["--no-egg-scan"]
  if body.get("no_fingerprint"):
    cmd += ["--no-fingerprint"]

  job = _start_job("telescope_probe", cmd, script.parent)
  _audit("eps_telescope_probe", {"ok": True, "job_id": job.job_id, "kind": job.kind})
  return _json({"ok": True, "job_id": job.job_id, "status": job.status})


async def api_eps_patch_probe(request: web.Request) -> web.Response:
  allowed, reason = _allowed("shell")
  if not allowed:
    return _json({"ok": False, "error": reason}, status=403)

  offroad = _offroad_reason()
  if offroad:
    return _json({"ok": False, "error": offroad}, status=403)

  try:
    body = await request.json()
  except Exception:
    body = {}

  if not body.get("confirm"):
    return _json({
      "ok": True,
      "needs_confirmation": True,
      "hint": "将停止 manager/pandad，对 EPS 8965B4512000 执行只读 probe。确认后继续。",
    })

  # Gate on telescope classification before starting a subprocess.
  tel = _eps_telescope_classify()
  classification = tel.get("classification") if tel.get("ok") else None
  if classification not in ("verified_variant", "already_patched"):
    return _json({
      "ok": False,
      "error": "eps-telescope 尚未判定为 verified_variant / already_patched，不能进入 eps_patch_probe。",
      "classification": classification,
      "next_step": "eps_telescope_probe",
    }, status=403)

  from ai.tools.domains.secoc.eps_patch_tools import EPS_PATCH_SCRIPT, _python

  script = EPS_PATCH_SCRIPT if EPS_PATCH_SCRIPT.exists() else Path("/data/eps-patch/app/eps_patch.py")
  cmd = [_python(), str(script), "probe"]
  serial = str(body.get("serial") or "")
  if serial:
    cmd += ["--serial", serial]

  job = _start_job("patch_probe", cmd, script.parent)
  _audit("eps_patch_probe", {"ok": True, "job_id": job.job_id, "kind": job.kind})
  return _json({"ok": True, "job_id": job.job_id, "status": job.status})


async def api_eps_job(request: web.Request) -> web.Response:
  job_id = request.match_info.get("job_id", "")
  job = _get_job(job_id)
  if job is None:
    return _json({"ok": False, "error": "job not found"}, status=404)
  return _json({"ok": True, "job": job.to_dict()})


async def api_eps_cancel_job(request: web.Request) -> web.Request:
  try:
    body = await request.json()
  except Exception:
    body = {}
  job_id = str(body.get("job") or "")
  job = _get_job(job_id)
  if job is None:
    return _json({"ok": False, "error": "job not found"}, status=404)
  with job._lock:
    job.cancelled = True
    if job._proc is not None:
      try:
        job._proc.terminate()
      except Exception:
        pass
    job.status = "cancelled"
  _audit("eps_cancel_job", {"ok": True, "job_id": job_id})
  return _json({"ok": True, "job_id": job_id, "status": "cancelled"})


async def api_eps_jobs(_request: web.Request) -> web.Response:
  with _JOBS_LOCK:
    payload = [j.to_dict() for j in _JOBS.values()]
  return _json({"ok": True, "jobs": payload})


def register_eps_routes(app: web.Application) -> None:
  app.router.add_get("/api/eps/status", api_eps_status)
  app.router.add_get("/api/eps/telescope-status", api_eps_telescope_status)
  app.router.add_get("/api/eps/telescope-classify", api_eps_telescope_classify)
  app.router.add_post("/api/eps/telescope-probe", api_eps_telescope_probe)
  app.router.add_post("/api/eps/patch-probe", api_eps_patch_probe)
  app.router.add_get("/api/eps/job/{job_id}", api_eps_job)
  app.router.add_get("/api/eps/jobs", api_eps_jobs)
  app.router.add_post("/api/eps/cancel-job", api_eps_cancel_job)
  app.router.add_get("/api/eps/prepare-patch", api_eps_prepare_patch)
  app.router.add_get("/api/eps/prepare-restore", api_eps_prepare_restore)
  app.router.add_get("/api/eps/diagnose", api_eps_diagnose)
