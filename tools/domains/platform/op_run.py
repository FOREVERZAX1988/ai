"""Shared helpers for wrapping openpilot tools/ scripts."""

from __future__ import annotations

import glob
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


def resolve_route_ref(route: str) -> str:
  route = (route or "").strip()
  if "|" in route or route.startswith("/") or (len(route) > 2 and route[1] == ":"):
    return route
  if "/" in route or "\\" in route:
    return route.replace("\\", "/")
  base = os.path.join(ROUTES_DIR, route)
  if os.path.isdir(base):
    # 标准布局: routeid/0/rlog
    if os.path.isdir(os.path.join(base, "0")):
      return f"{route}/0"
    # 本机(sunnypilot)布局: segment 在目录名, rlog 直接放目录内 -> 绝对路径交给 LogReader
    for name in ("rlog.zst", "rlog", "qlog.zst", "qlog"):
      p = os.path.join(base, name)
      if os.path.isfile(p):
        return p
    return f"{route}/0"
  # 本机布局 route 名不带段号(如 00000004--915ebf086f): 匹配 {route}--* 段目录,
  # 返回序号最小段的 rlog 绝对路径; LogReader 不接受相对路径/无段 route 名
  segments = sorted(
    glob.glob(os.path.join(ROUTES_DIR, route + "--*")),
    key=lambda p: _segment_index(p),
  )
  if segments:
    first = segments[0]
    for name in ("rlog.zst", "rlog", "qlog.zst", "qlog"):
      p = os.path.join(first, name)
      if os.path.isfile(p):
        return p
    return first
  return route


def _segment_index(path: str) -> int:
  """Extract trailing segment number from local layout dir name (…--N)."""
  name = os.path.basename(path).rstrip("/")
  idx = name.rfind("--")
  if idx >= 0:
    try:
      return int(name[idx + 2:])
    except ValueError:
      pass
  return 0


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
