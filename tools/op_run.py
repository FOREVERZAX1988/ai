"""Shared helpers for wrapping openpilot tools/ scripts."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from ai.system.paths import openpilot_root, routes_dir

OPENPILOT_ROOT = openpilot_root()
ROUTES_DIR = routes_dir()
MAX_OUTPUT_CHARS = 48_000


def validate_route_ref(route: str) -> str | None:
  route = (route or "").strip()
  if not route:
    return "route is required"
  if ".." in route:
    return "Invalid route (path traversal)"
  return None


def _local_route_segments(route: str) -> list[str]:
  """Return existing local segment dirs for a route name.

  openpilot on-device stores routes as ROUTES_DIR/<route>--<seg> (e.g.
  00000008--ecf1605f1b--0). The route name itself (without --seg) is NOT a
  directory, so resolve_route_ref must map it to the actual segment dirs.
  """
  import glob
  base = os.path.join(ROUTES_DIR, route)
  if os.path.isdir(base):
    return [base]
  return sorted(glob.glob(base + "--*"))


def resolve_route_ref(route: str) -> str:
  route = (route or "").strip()
  if "|" in route or route.startswith("/") or (len(route) > 2 and route[1] == ":"):
    return route
  if "/" in route or "\\" in route:
    return route.replace("\\", "/")
  segs = _local_route_segments(route)
  if segs:
    # Local route folder: hand back a real log file inside the first segment
    # dir. LogReader's parse_direct() only accepts existing files, not dirs.
    for seg in segs:
      log = _first_log_file(seg)
      if log:
        return log
    return segs[0]
  return route


def _first_log_file(seg_dir: str) -> str | None:
  """Return the first existing rlog/qlog file in a segment dir (rlog preferred)."""
  import glob
  for pat in ("rlog*", "qlog*"):
    for f in sorted(glob.glob(os.path.join(seg_dir, pat))):
      name = os.path.basename(f)
      if name.startswith(("rlog", "qlog")) and not name.endswith(".lock") and os.path.isfile(f):
        return f
  return None


def expand_local_route_files(route: str) -> list[str]:
  """Expand a local route name to the list of log files across all segments."""
  route = (route or "").strip()
  segs = _local_route_segments(route)
  if not segs:
    return []
  out: list[str] = []
  for seg in segs:
    log = _first_log_file(seg)
    if log:
      out.append(log)
  return out


def build_openpilot_env() -> dict[str, str]:
  env = os.environ.copy()
  env.setdefault("PYTHONPATH", str(OPENPILOT_ROOT))
  if str(OPENPILOT_ROOT) not in env["PYTHONPATH"].split(os.pathsep):
    env["PYTHONPATH"] = str(OPENPILOT_ROOT) + os.pathsep + env["PYTHONPATH"]
  env.setdefault("MPLBACKEND", "Agg")
  return env


def run_subprocess(
  cmd: list[str],
  *,
  timeout: int = 360,
  cwd: Path | None = None,
) -> dict[str, Any]:
  try:
    proc = subprocess.run(
      cmd,
      capture_output=True,
      text=True,
      timeout=timeout,
      cwd=str(cwd or OPENPILOT_ROOT),
      env=build_openpilot_env(),
    )
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if len(stdout) > MAX_OUTPUT_CHARS:
      stdout = stdout[:MAX_OUTPUT_CHARS] + "\n... [truncated] ..."
    if len(stderr) > 8000:
      stderr = stderr[:8000] + "\n... [truncated] ..."
    return {
      "ok": proc.returncode == 0,
      "returncode": proc.returncode,
      "stdout": stdout,
      "stderr": stderr,
    }
  except subprocess.TimeoutExpired:
    return {"ok": False, "error": f"Command timed out after {timeout}s", "stdout": "", "stderr": ""}
  except Exception as e:
    return {"ok": False, "error": str(e), "stdout": "", "stderr": ""}


def parse_report_path(stdout: str) -> str | None:
  for line in stdout.splitlines():
    if "Opening report:" in line:
      return line.split("Opening report:", 1)[-1].strip()
  return None
