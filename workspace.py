"""Workspace markdown files under <openpilot>/workspace/ — USER, MEMORY, SOUL, fork profile."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ai.system.paths import openpilot_root, workspace_path

_FILE_MAP: dict[str, str] = {
  "user": "USER.md",
  "memory": "MEMORY.md",
  "soul": "SOUL.md",
  "agents": "AGENTS.md",
  "tools": "TOOLS.md",
  "heartbeat": "HEARTBEAT.md",
  "fork": "FORK_PROFILE.md",
}

_DEFAULTS: dict[str, str] = {
  "USER.md": "# User profile\n\n（在此记录车型、偏好与常用 workflow。）\n",
  "MEMORY.md": "# Memory\n\n（长期记忆摘要。）\n",
  "SOUL.md": "# Soul\n\n（助手语气与人设，可选。）\n",
  "FORK_PROFILE.md": "# Fork profile\n\n（安装后由 op助手 自动写入当前 openpilot 分支摘要；也可手动编辑。）\n",
}


def workspace_dir() -> Path:
  return workspace_path("workspace", mkdir=True)


def _resolve_key(key: str) -> str | None:
  key = (key or "").strip().lower()
  if not key:
    return None
  if key.endswith(".md"):
    return key
  return _FILE_MAP.get(key)


def list_workspace_files() -> list[dict[str, str]]:
  base = workspace_dir()
  out: list[dict[str, str]] = []
  for logical, filename in _FILE_MAP.items():
    path = base / filename
    out.append({
      "key": logical,
      "filename": filename,
      "exists": path.is_file(),
      "path": str(path),
    })
  return out


def read_workspace_file(key: str) -> str:
  filename = _resolve_key(key)
  if not filename:
    return ""
  path = workspace_dir() / filename
  if not path.is_file():
    return ""
  try:
    return path.read_text(encoding="utf-8")
  except OSError:
    return ""


def write_workspace_file(key: str, content: str) -> dict[str, Any]:
  filename = _resolve_key(key)
  if not filename:
    return {"ok": False, "error": "unknown workspace key"}
  base = workspace_dir()
  path = base / filename
  try:
    path.write_text(content or "", encoding="utf-8")
  except OSError as exc:
    return {"ok": False, "error": str(exc)}
  return {"ok": True, "key": key, "filename": filename, "path": str(path)}


def ensure_default_workspace_files() -> None:
  base = workspace_dir()
  for filename, default in _DEFAULTS.items():
    path = base / filename
    if not path.is_file():
      path.write_text(default, encoding="utf-8")


def workspace_prompt_blocks(*, max_chars: int = 2500) -> list[str]:
  blocks: list[str] = []
  for logical in ("user", "memory", "soul", "fork"):
    text = read_workspace_file(logical).strip()
    if not text or len(text) < 8:
      continue
    label = logical.upper() if logical != "fork" else "FORK_PROFILE"
    blocks.append(f"## Workspace {label}\n{text[:max_chars]}")
  return blocks
