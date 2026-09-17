"""aiohttp routes for EPS telescope / 8965B4512000 patch panel.

Design constraints (keep the brick risk as low as possible):

- All probe operations are read-only but stop manager/pandad; they run in a
  background thread pool and are polled by the UI.
- The destructive ``patch`` / ``restore`` writers are exposed as HTTP endpoints
  ONLY through a pty-based runner that automates the required YES confirmation.
  They still require offroad + is_action_allowed('shell') + double confirmation.
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

try:
  from openpilot.common.swaglog import cloudlog
except Exception:
  cloudlog = None

from ai.server.deps import get_state_reader, json_response, params
try:
  from ai.system.admin import is_admin_mode
except Exception:
  def is_admin_mode(_params=None):
    return True
try:
  from ai.system.safety import is_action_allowed
except Exception:
  def is_action_allowed(cap: str):
    return cap == "shell"
from ai.tools.domains.secoc.eps_patch_tools import (
  WriterRunner,
  _openpilot_running,
  _stop_openpilot,
  eps_patch_diagnose as _eps_patch_diagnose,
  eps_patch_export_backup as _eps_patch_export_backup,
  eps_patch_import_backup as _eps_patch_import_backup,
  eps_patch_prepare_patch as _eps_patch_prepare_patch,
  eps_patch_prepare_restore as _eps_patch_prepare_restore,
  eps_patch_probe as _eps_patch_probe,
  eps_patch_run_writer as _eps_patch_run_writer,
  eps_patch_status as _eps_patch_status,
  eps_patch_validate_backup as _eps_patch_validate_backup,
  eps_telescope_classify as _eps_telescope_classify,
  eps_telescope_probe as _eps_telescope_probe,
  eps_telescope_status as _eps_telescope_status,
  list_pandas as _list_pandas,
)
from ai.tools.domains.platform.audit_store import record_audit


try:
  _PARAMS = params()
except Exception:
  _PARAMS = None


def _json(data: dict, *, status: int = 200) -> web.Response:
  return web.json_response(data, status=status)


# ---------------------------------------------------------------------------
# In-memory job registry. Jobs hold stdout/stderr lines streamed from the
# underlying subprocess. All writer operations are refused at the API layer.
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _Job:
  job_id: str
  kind: str  # "telescope_probe" | "patch_probe" | "patch_writer" | "restore_writer"
  command: list[str]
  cwd: Path
  status: str  # "pending" | "running" | "done" | "error" | "cancelled" | "power_cycle"
  returncode: int | None = None
  lines: list[dict[str, str]] = dataclasses.field(default_factory=list)
  error: str = ""
  cancelled: bool = False
  power_cycle_seen: bool = False
  yes_sent: bool = False
  stage_after: str | None = None
  _proc: subprocess.Popen[str] | None = None
  _runner: WriterRunner | None = None
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
        "power_cycle_seen": self.power_cycle_seen,
        "yes_sent": self.yes_sent,
        "stage_after": self.stage_after,
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


def _start_writer_job(kind: str, command: str, serial: str) -> _Job:
  """Start a pty-based patch/restore writer job."""
  job_id = uuid.uuid4().hex[:12]
  script = _eps_patch_script()
  job = _Job(
    job_id=job_id,
    kind=kind,
    command=[_python(), str(script), command],
    cwd=script.parent,
  )
  with _JOBS_LOCK:
    _JOBS[job_id] = job

  def on_line(line: str) -> None:
    with job._lock:
      job.lines.append({"t": f"{time.monotonic():.3f}", "line": line})

  runner = WriterRunner(command, serial=serial, on_line=on_line)
  job._runner = runner

  def writer_worker() -> None:
    try:
      with job._lock:
        if job.cancelled:
          job.status = "cancelled"
          return
        job.status = "running"
      result = runner.run()
      with job._lock:
        job.returncode = result.get("returncode")
        job.power_cycle_seen = result.get("power_cycle_seen", False)
        job.yes_sent = result.get("yes_sent", False)
        job.stage_after = result.get("stage_after")
        if job.cancelled:
          job.status = "cancelled"
        elif result.get("power_cycle_seen") and result.get("returncode") == 0:
          job.status = "power_cycle"
        elif result.get("ok"):
          job.status = "done"
        else:
          job.status = "error"
          job.error = result.get("error") or "writer failed"
    except Exception as exc:
      cloudlog.exception("eps writer job failed")
      with job._lock:
        job.error = str(exc)
        job.status = "error"

  thread = threading.Thread(target=writer_worker, daemon=True)
  thread.start()
  return job


def _eps_patch_script() -> Path:
  from ai.tools.domains.secoc.eps_patch_tools import EPS_PATCH_SCRIPT
  if EPS_PATCH_SCRIPT.exists():
    return EPS_PATCH_SCRIPT
  return Path("/data/eps-patch/app/eps_patch.py")


def _python() -> str:
  from ai.tools.domains.secoc.eps_patch_tools import _python as py
  return py()


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
  # Append a resumable checkpoint hint so the UI can offer "continue".
  state = status.get("state") or {}
  stage = status.get("stage")
  power_cycle = state.get("power_cycle") if isinstance(state, dict) else None
  if power_cycle and stage not in (None, "PASS"):
    status["power_cycle_checkpoint"] = {
      "completed_state": power_cycle.get("completed_state"),
      "next_state": power_cycle.get("next_state"),
      "hint": "writer 已保存 checkpoint 并退出；请完全断电重启 comma/EPS，然后点击“继续刷写”恢复同一命令。",
    }
  elif status.get("state_name") == "patch_in_progress":
    status["continue_hint"] = "patch 流程已部分执行；可点击“继续刷写”恢复同一命令。"
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


async def api_eps_cancel_job(request: web.Request) -> web.Response:
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
    if job._runner is not None:
      try:
        if job._runner.proc is not None and job._runner.proc.poll() is None:
          job._runner.proc.terminate()
      except Exception:
        pass
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


async def _read_json_body(request: web.Request) -> dict[str, Any]:
  try:
    body = await request.json()
    return body if isinstance(body, dict) else {}
  except Exception:
    return {}


def _writer_request_gate(request: web.Request, *, require_backup: bool = False, check_openpilot: bool = True) -> tuple[dict[str, Any] | None, dict[str, Any]]:
  """Common permission/confirmation gate for patch/restore writer endpoints."""
  allowed, reason = _allowed("shell")
  if not allowed:
    return {"ok": False, "error": reason}, {}

  offroad = _offroad_reason()
  if offroad:
    return {"ok": False, "error": offroad}, {}

  if check_openpilot:
    op_status = _openpilot_running()
    if op_status.get("running"):
      return {
        "ok": False,
        "error": "openpilot 主流程仍在运行，刷写 EPS 前必须先停止。请点击面板上的“停止 openpilot”按钮。",
        "needs_stop_openpilot": True,
        "openpilot_status": op_status,
      }, {}

  if require_backup:
    from ai.tools.domains.secoc.eps_patch_tools import _backup_info
    info = _backup_info()
    if not info.get("available"):
      return {
        "ok": False,
        "error": "未检测到有效的原车 EPS 备份，无法执行刷写/恢复。请先运行 Probe 或导入备份。",
        "next_step": "eps_patch_probe",
      }, {}

  return None, {}


async def api_eps_patch_writer(request: web.Request) -> web.Response:
  err, _ = _writer_request_gate(request, require_backup=True)
  if err:
    return _json(err, status=403)
  body = await _read_json_body(request)

  if not body.get("confirm"):
    return _json({
      "ok": True,
      "needs_confirmation": True,
      "hint": "将执行 EPS 8965B4512000 patch writer，会擦写 EPS Flash，失败可能变砖。确认后继续。",
    })

  if body.get("i_understand") != "brick_risk":
    return _json({
      "ok": False,
      "error": "缺少二次确认：请在面板勾选“我已了解变砖风险”后再执行。",
    }, status=403)

  serial = str(body.get("serial") or "")
  job = _start_writer_job("patch_writer", "patch", serial)
  _audit("eps_patch_writer", {"ok": True, "job_id": job.job_id, "kind": job.kind})
  return _json({"ok": True, "job_id": job.job_id, "status": job.status})


async def api_eps_restore_writer(request: web.Request) -> web.Response:
  err, _ = _writer_request_gate(request, require_backup=True)
  if err:
    return _json(err, status=403)
  body = await _read_json_body(request)

  if not body.get("confirm"):
    return _json({
      "ok": True,
      "needs_confirmation": True,
      "hint": "将执行 EPS restore writer，把 EPS 恢复到 probe 时的原车备份。失败也可能变砖。确认后继续。",
    })

  if body.get("i_understand") != "brick_risk":
    return _json({
      "ok": False,
      "error": "缺少二次确认：请在面板勾选“我已了解变砖风险”后再执行。",
    }, status=403)

  serial = str(body.get("serial") or "")
  job = _start_writer_job("restore_writer", "restore", serial)
  _audit("eps_restore_writer", {"ok": True, "job_id": job.job_id, "kind": job.kind})
  return _json({"ok": True, "job_id": job.job_id, "status": job.status})


async def api_eps_openpilot_status(_request: web.Request) -> web.Response:
  """Return whether comma/openpilot is still running (and would block Panda)."""
  result = await _run_sync(_openpilot_running)
  return _json(result)


async def api_eps_stop_openpilot(request: web.Request) -> web.Response:
  """Stop comma/openpilot so EPS tools can open Panda hardware.

  Requires the same shell capability as the writers and double confirmation.
  """
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
      "hint": "将停止 comma/openpilot 主流程（tmux kill-session -t comma）并结束所有 pandad 进程。停止后无法开车，确认后继续。",
    })

  if body.get("i_understand") != "stop_openpilot":
    return _json({
      "ok": False,
      "error": "缺少二次确认：请在面板勾选“我已了解停止 openpilot 的后果”后再执行。",
    }, status=403)

  result = await _run_sync(_stop_openpilot)
  _audit("eps_stop_openpilot", result)
  if not result.get("ok"):
    return _json(result, status=500)
  return _json(result)


async def api_eps_panda_list(_request: web.Request) -> web.Response:
  result = await _run_sync(_list_pandas)
  return _json(result)


async def api_eps_backup_info(_request: web.Request) -> web.Response:
  from ai.tools.domains.secoc.eps_patch_tools import _backup_info
  info = await _run_sync(_backup_info)
  return _json({"ok": True, **info})


async def api_eps_backup_download(request: web.Request) -> web.Response:
  """Download one backup file by name (target, crc, metadata)."""
  name = request.match_info.get("name", "")
  probe_dir = Path("/data/eps-patch/artifacts/probe")
  mapping = {
    "target": probe_dir / "original-sector-0x88000.bin",
    "crc": probe_dir / "original-sector-0xf8000.bin",
    "metadata": probe_dir / "recovery-metadata.json",
  }
  path = mapping.get(name)
  if path is None or not path.exists():
    return _json({"ok": False, "error": "backup file not found"}, status=404)

  try:
    data = path.read_bytes()
  except Exception as exc:
    return _json({"ok": False, "error": str(exc)}, status=500)

  headers = {
    "Content-Type": "application/octet-stream",
    "Content-Disposition": f"attachment; filename={path.name}",
  }
  return web.Response(body=data, headers=headers)


async def api_eps_backup_export(_request: web.Request) -> web.Response:
  """Export the current probe backup as a packaged archive with manifest."""
  from ai.tools.domains.secoc.eps_patch_tools import _load_backup_metadata
  metadata = _load_backup_metadata(_artifact_root() / "probe")
  vin = metadata.get("vin", "UNKNOWN") or "UNKNOWN"
  variant = metadata.get("variant", "")
  result = _eps_patch_export_backup(vin=vin, variant=variant)
  if not result.get("ok"):
    return _json(result, status=400)
  path = Path(result["path"])
  try:
    data = path.read_bytes()
  except Exception as exc:
    return _json({"ok": False, "error": str(exc)}, status=500)
  headers = {
    "Content-Type": "application/gzip",
    "Content-Disposition": f"attachment; filename={path.name}",
  }
  _audit("eps_backup_export", {"ok": True, "path": str(path)})
  return web.Response(body=data, headers=headers)


async def api_eps_backup_import(request: web.Request) -> web.Response:
  """Import an external backup archive into the probe artifact directory."""
  reader = await request.multipart()
  files: dict[str, bytes] = {}
  try:
    while True:
      part = await reader.next()
      if part is None:
        break
      name = part.name or ""
      if name == "archive":
        payload = await part.read(decode=True)
        try:
          import tarfile
          import io
          with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
            for member in tar.getmembers():
              if member.isfile():
                key = None
                if member.name == "original-sector-0x88000.bin":
                  key = "target"
                elif member.name == "original-sector-0xf8000.bin":
                  key = "crc"
                elif member.name == "recovery-metadata.json":
                  key = "metadata"
                elif member.name == "manifest.json":
                  key = "manifest"
                if key:
                  files[key] = tar.extractfile(member).read()
        except Exception as exc:
          return _json({"ok": False, "error": f"invalid archive: {exc}"}, status=400)
      elif name in ("target", "crc", "metadata"):
        files[name] = await part.read(decode=True)
  except Exception as exc:
    return _json({"ok": False, "error": f"upload failed: {exc}"}, status=400)

  if not {"target", "crc", "metadata"}.issubset(files.keys()):
    return _json({"ok": False, "error": "missing required backup files"}, status=400)

  result = _eps_patch_import_backup(
    files,
    expected_part_number="8965B4512000",
  )
  _audit("eps_backup_import", {"ok": result.get("ok"), "error": result.get("error")})
  if not result.get("ok"):
    return _json(result, status=400)
  return _json({"ok": True, "path": result["path"], "validation": result["validation"]})


async def api_eps_backup_history(_request: web.Request) -> web.Response:
  """List archived backup snapshots under the artifact root."""
  root = Path("/data/eps-patch/artifacts")
  history_dir = root / "history"
  entries = []
  if history_dir.exists():
    for path in sorted(history_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
      if path.suffix in (".gz", ".tar.gz") or path.name.startswith("snapshot-"):
        try:
          st = path.stat()
          entries.append({
            "name": path.name,
            "path": str(path),
            "size": st.st_size,
            "mtime": st.st_mtime,
          })
        except OSError:
          pass
  return _json({"ok": True, "entries": entries[:20]})


async def api_eps_audit(_request: web.Request) -> web.Response:
  """Return recent EPS-related audit entries."""
  from ai.tools.domains.platform.audit_store import list_audit_trail
  result = list_audit_trail(limit=100)
  if not result.get("ok"):
    return _json(result, status=500)
  eps_entries = [e for e in result.get("entries", []) if str(e.get("action", "")).startswith("eps_")]
  return _json({"ok": True, "entries": eps_entries, "count": len(eps_entries)})


async def api_eps_snapshot(request: web.Request) -> web.Response:
  """Create a pre-patch snapshot of the current EPS sectors (read-only).

  This is a safety net: before a destructive writer runs we re-read the current
  EPS state and archive it separately from the probe backup.
  """
  err, _ = _writer_request_gate(request)
  if err:
    return _json(err, status=403)
  result = await _run_sync(_eps_patch_run_writer, command="snapshot", serial="")
  return _json(result)


def register_eps_routes(app: web.Application) -> None:
  app.router.add_get("/api/eps/status", api_eps_status)
  app.router.add_get("/api/eps/telescope-status", api_eps_telescope_status)
  app.router.add_get("/api/eps/telescope-classify", api_eps_telescope_classify)
  app.router.add_post("/api/eps/telescope-probe", api_eps_telescope_probe)
  app.router.add_post("/api/eps/patch-probe", api_eps_patch_probe)
  app.router.add_post("/api/eps/patch-writer", api_eps_patch_writer)
  app.router.add_post("/api/eps/restore-writer", api_eps_restore_writer)
  app.router.add_get("/api/eps/job/{job_id}", api_eps_job)
  app.router.add_get("/api/eps/jobs", api_eps_jobs)
  app.router.add_post("/api/eps/cancel-job", api_eps_cancel_job)
  app.router.add_get("/api/eps/prepare-patch", api_eps_prepare_patch)
  app.router.add_get("/api/eps/prepare-restore", api_eps_prepare_restore)
  app.router.add_get("/api/eps/diagnose", api_eps_diagnose)
  app.router.add_get("/api/eps/openpilot-status", api_eps_openpilot_status)
  app.router.add_post("/api/eps/stop-openpilot", api_eps_stop_openpilot)
  app.router.add_get("/api/eps/panda-list", api_eps_panda_list)
  app.router.add_get("/api/eps/backup-info", api_eps_backup_info)
  app.router.add_get("/api/eps/backup/{name}", api_eps_backup_download)
  app.router.add_get("/api/eps/backup-export", api_eps_backup_export)
  app.router.add_post("/api/eps/backup-import", api_eps_backup_import)
  app.router.add_get("/api/eps/backup-history", api_eps_backup_history)
  app.router.add_get("/api/eps/audit", api_eps_audit)
  app.router.add_post("/api/eps/snapshot", api_eps_snapshot)
