"""Platform backup / export / restore — memory, sessions, skills, MCP, workspace."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from openpilot.common.params import Params

from ai.common.storage import read_param, write_param
from ai.mcp.host import MCP_SERVERS_KEY, _load_servers as _load_mcp
from ai.tools.memory_store import NOTES_KEY, PROFILE_KEY, get_memory
from ai.tools.session_store import SESSIONS_KEY, get_sessions
from ai.tools.skill_learning import LEARNED_KEY, _load as _load_learned
from ai.workspace import _FILE_MAP, list_workspace_files, read_workspace_file, write_workspace_file, workspace_dir

BUNDLE_VERSION = 1
_EXPORTS_DIR = Path(__file__).resolve().parent.parent / "data" / "exports"

# Params copied on export (tokens redacted unless include_secrets).
_PARAM_KEYS = [
  "ai_context_window",
  "ai_compaction_enabled",
  "ai_compact_after_turns",
  "ai_keep_recent_turns",
  "ai_reserve_tokens",
  "ai_compaction_token_trigger",
  "ai_github_actions_pat",
  "ai_gitee_token",
  "ai_publish_config",
  "ai_issue_publish",
]

_SECRET_KEYS = {"ai_github_actions_pat", "ai_gitee_token"}


def _redact(value: str) -> str:
  if not value:
    return ""
  if len(value) <= 8:
    return "***"
  return value[:4] + "…" + value[-4:]


def _read_param_map(params: Params, *, include_secrets: bool) -> dict[str, str]:
  out: dict[str, str] = {}
  for key in _PARAM_KEYS:
    raw = read_param(params, key)
    if isinstance(raw, bytes):
      raw = raw.decode("utf-8", errors="replace")
    text = str(raw or "")
    if key in _SECRET_KEYS and text and not include_secrets:
      out[key] = _redact(text)
      out[f"{key}__redacted"] = True
    else:
      out[key] = text
  return out


def _workspace_bundle() -> dict[str, str]:
  files: dict[str, str] = {}
  for logical in _FILE_MAP:
    content = read_workspace_file(logical)
    if content:
      files[logical] = content
  return files


def _learned_skill_files(params: Params) -> dict[str, str]:
  base = Path(__file__).resolve().parent.parent
  out: dict[str, str] = {}
  for entry in _load_learned(params):
    rel = str(entry.get("path") or "")
    if not rel:
      continue
    path = base / rel
    if path.is_file():
      out[rel.replace("\\", "/")] = path.read_text(encoding="utf-8", errors="replace")
  return out


def build_platform_bundle(params: Params | None = None, *, include_secrets: bool = False) -> dict[str, Any]:
  """Assemble a portable JSON bundle of platform state."""
  params = params or Params()
  mem = get_memory(params)
  sessions = get_sessions(params)
  return {
    "ok": True,
    "bundle": {
      "version": BUNDLE_VERSION,
      "exportedAt": int(time.time()),
      "includeSecrets": include_secrets,
      "memory": {
        "notes": mem.get("notes") or [],
        "vehicle_profile": mem.get("vehicle_profile") or {},
      },
      "sessions": {
        "sessions": sessions.get("sessions") or [],
        "activeId": sessions.get("activeId"),
        "savedAt": sessions.get("savedAt"),
      },
      "learned_skills": _load_learned(params),
      "learned_skill_files": _learned_skill_files(params),
      "mcp_servers": _load_mcp(params),
      "workspace": _workspace_bundle(),
      "params": _read_param_map(params, include_secrets=include_secrets),
    },
    "manifest": backup_manifest(params),
  }


def backup_manifest(params: Params | None = None) -> dict[str, Any]:
  params = params or Params()
  mem = get_memory(params)
  ws = list_workspace_files()
  return {
    "version": BUNDLE_VERSION,
    "memoryNotes": len(mem.get("notes") or []),
    "sessions": len((get_sessions(params).get("sessions") or [])),
    "learnedSkills": len(_load_learned(params)),
    "mcpServers": len(_load_mcp(params)),
    "workspaceFiles": sum(1 for f in ws if f.get("exists")),
    "workspaceKeys": [f.get("key") for f in ws if f.get("exists")],
  }


def export_platform_bundle(
  params: Params | None = None,
  *,
  include_secrets: bool = False,
  write_file: bool = True,
) -> dict[str, Any]:
  """Export bundle; optionally persist under ai/data/exports for download."""
  params = params or Params()
  result = build_platform_bundle(params, include_secrets=include_secrets)
  bundle = result["bundle"]
  if not write_file:
    return {**result, "download": None}

  _EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
  stamp = time.strftime("%Y%m%d-%H%M%S")
  name = f"platform-backup-{stamp}.json"
  path = _EXPORTS_DIR / name
  path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
  return {
    **result,
    "download": {
      "filename": name,
      "path": str(path),
      "url": f"/api/ai/dev-assets/exports/{name}",
      "bytes": path.stat().st_size,
    },
  }


def _merge_notes(existing: list, incoming: list, *, mode: str) -> list:
  if mode == "replace":
    return incoming
  seen = {n.get("id") for n in existing if n.get("id")}
  merged = list(existing)
  for n in incoming:
    if n.get("id") and n["id"] in seen:
      continue
    merged.append(n)
  return merged[:80]


def restore_platform_bundle(
  params: Params,
  bundle: dict[str, Any],
  *,
  mode: str = "merge",
  sections: list[str] | None = None,
  confirm: bool = False,
) -> dict[str, Any]:
  """Restore from bundle. mode: merge | replace. sections limits what is applied."""
  if not confirm:
    inner = bundle.get("bundle") if isinstance(bundle.get("bundle"), dict) else bundle
    return {
      "ok": True,
      "needs_confirmation": True,
      "preview": {
        "version": inner.get("version"),
        "exportedAt": inner.get("exportedAt"),
        "sections": sections or ["memory", "sessions", "learned_skills", "mcp_servers", "workspace", "params"],
        "manifest": {
          "memoryNotes": len((inner.get("memory") or {}).get("notes") or []),
          "sessions": len((inner.get("sessions") or {}).get("sessions") or []),
          "learnedSkills": len(inner.get("learned_skills") or []),
          "mcpServers": len(inner.get("mcp_servers") or []),
          "workspaceFiles": len(inner.get("workspace") or {}),
        },
      },
      "hint": "Set confirm=true to apply restore.",
    }

  data = bundle.get("bundle") if isinstance(bundle.get("bundle"), dict) else bundle
  if not isinstance(data, dict):
    return {"ok": False, "error": "invalid bundle"}
  if int(data.get("version") or 0) != BUNDLE_VERSION:
    return {"ok": False, "error": f"unsupported bundle version (expected {BUNDLE_VERSION})"}

  allowed = set(sections or ["memory", "sessions", "learned_skills", "mcp_servers", "workspace", "params"])
  applied: list[str] = []

  if "memory" in allowed and isinstance(data.get("memory"), dict):
    mem = data["memory"]
    cur = get_memory(params)
    notes = mem.get("notes") or []
    profile = mem.get("vehicle_profile") or {}
    if mode == "replace":
      write_param(params, NOTES_KEY, json.dumps(notes[:80], ensure_ascii=False))
      write_param(params, PROFILE_KEY, json.dumps(profile, ensure_ascii=False))
    else:
      cur_notes = cur.get("notes") or []
      merged = _merge_notes(cur_notes, notes, mode="merge")
      write_param(params, NOTES_KEY, json.dumps(merged, ensure_ascii=False))
      cur_profile = cur.get("vehicle_profile") or {}
      cur_profile.update({k: v for k, v in profile.items() if v is not None})
      write_param(params, PROFILE_KEY, json.dumps(cur_profile, ensure_ascii=False))
    applied.append("memory")

  if "sessions" in allowed and isinstance(data.get("sessions"), dict):
    sess = data["sessions"]
    if mode == "replace":
      write_param(params, SESSIONS_KEY, json.dumps(sess, ensure_ascii=False))
    else:
      cur = get_sessions(params)
      cur_ids = {s.get("id") for s in cur.get("sessions") or []}
      merged_sessions = list(cur.get("sessions") or [])
      for s in sess.get("sessions") or []:
        if s.get("id") not in cur_ids:
          merged_sessions.append(s)
      write_param(params, SESSIONS_KEY, json.dumps({
        "sessions": merged_sessions[:30],
        "activeId": cur.get("activeId") or sess.get("activeId"),
        "savedAt": int(time.time()),
      }, ensure_ascii=False))
    applied.append("sessions")

  if "learned_skills" in allowed:
    skills = data.get("learned_skills") or []
    if mode == "replace":
      write_param(params, LEARNED_KEY, json.dumps(skills[:24], ensure_ascii=False))
    else:
      cur = _load_learned(params)
      cur_ids = {s.get("id") for s in cur}
      for s in skills:
        if s.get("id") not in cur_ids:
          cur.insert(0, s)
      write_param(params, LEARNED_KEY, json.dumps(cur[:24], ensure_ascii=False))
    base = Path(__file__).resolve().parent.parent
    for rel, content in (data.get("learned_skill_files") or {}).items():
      path = base / rel
      path.parent.mkdir(parents=True, exist_ok=True)
      if mode == "replace" or not path.is_file():
        path.write_text(content, encoding="utf-8")
    applied.append("learned_skills")

  if "mcp_servers" in allowed:
    servers = data.get("mcp_servers") or []
    if mode == "replace":
      write_param(params, MCP_SERVERS_KEY, json.dumps(servers[:16], ensure_ascii=False))
    else:
      cur = _load_mcp(params)
      cur_ids = {s.get("id") for s in cur}
      for s in servers:
        if s.get("id") not in cur_ids:
          cur.append(s)
      write_param(params, MCP_SERVERS_KEY, json.dumps(cur[:16], ensure_ascii=False))
    applied.append("mcp_servers")

  if "workspace" in allowed and isinstance(data.get("workspace"), dict):
    for key, content in data["workspace"].items():
      if mode == "replace" or not read_workspace_file(key).strip():
        write_workspace_file(key, str(content or ""))
    applied.append("workspace")

  if "params" in allowed and isinstance(data.get("params"), dict):
    for key, value in data["params"].items():
      if key.endswith("__redacted"):
        continue
      if key in _SECRET_KEYS and data["params"].get(f"{key}__redacted"):
        continue
      if key in _PARAM_KEYS and value is not None:
        write_param(params, key, str(value))
    applied.append("params")

  try:
    from ai.tools.session_index import rebuild_from_params
    rebuild_from_params(params)
  except Exception:
    pass

  return {"ok": True, "applied": applied, "mode": mode}


def parse_uploaded_bundle(text: str) -> dict[str, Any]:
  try:
    data = json.loads(text)
  except json.JSONDecodeError as exc:
    return {"ok": False, "error": f"invalid JSON: {exc}"}
  if isinstance(data, dict) and "bundle" in data:
    return {"ok": True, "bundle": data}
  if isinstance(data, dict) and data.get("version"):
    return {"ok": True, "bundle": {"bundle": data}}
  return {"ok": False, "error": "not a platform backup bundle"}
