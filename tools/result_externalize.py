"""Externalize large tool results — keep context lean, store on disk."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from ai.common.storage import read_param_bool
from ai.system.paths import workspace_path

_DEFAULT_THRESHOLD = 8192
_MAX_PREVIEW = 2000


def externalize_enabled(params: Any = None) -> bool:
  return read_param_bool(params, "ai_externalize_results", True)


def threshold_bytes(params: Any = None) -> int:
  try:
    from ai.common.storage import read_param
    raw = read_param(params, "ai_externalize_threshold", str(_DEFAULT_THRESHOLD))
    return max(1024, min(int(str(raw or _DEFAULT_THRESHOLD)), 512_000))
  except (TypeError, ValueError):
    return _DEFAULT_THRESHOLD


def _results_dir(session_id: str) -> Path:
  sid = (session_id or "global").replace("/", "_").replace("\\", "_")[:64]
  path = workspace_path("tool_results", sid, mkdir=True)
  path.mkdir(parents=True, exist_ok=True)
  return path


def _summarize(result: Any, *, max_len: int = 600) -> str:
  if isinstance(result, dict):
    if result.get("error"):
      return f"Error: {str(result.get('error'))[:max_len]}"
    if result.get("summary"):
      return str(result["summary"])[:max_len]
    keys = list(result.keys())[:8]
    return f"Dict keys: {', '.join(keys)}"[:max_len]
  text = str(result)
  return text[:max_len] + ("…" if len(text) > max_len else "")


def externalize_if_needed(
  result: Any,
  *,
  session_id: str = "",
  tool_name: str = "",
  params: Any = None,
) -> tuple[Any, dict[str, Any] | None]:
  """
  Return (result_for_context, artifact_meta_or_none).
  If externalized, result_for_context is a compact pointer dict.
  """
  if not externalize_enabled(params):
    return result, None
  try:
    serialized = json.dumps(result, ensure_ascii=False, default=str)
  except (TypeError, ValueError):
    return result, None
  if len(serialized.encode("utf-8")) <= threshold_bytes(params):
    return result, None

  ref_id = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
  path = _results_dir(session_id) / f"{tool_name or 'tool'}_{ref_id}.json"
  try:
    path.write_text(serialized, encoding="utf-8")
  except OSError:
    # Fallback: truncate inline
    preview = serialized[:_MAX_PREVIEW]
    return {
      "ok": True,
      "externalized": False,
      "truncated": True,
      "preview": preview,
      "size_bytes": len(serialized),
    }, None

  preview = serialized[:_MAX_PREVIEW]
  pointer = {
    "ok": True,
    "externalized": True,
    "ref": f"toolresult://{ref_id}",
    "path": str(path),
    "tool": tool_name,
    "size_bytes": len(serialized),
    "summary": _summarize(result),
    "preview": preview,
    "hint": "Full output saved to disk. Use read_file on path if you need the complete data.",
  }
  artifact = {
    "id": f"ext_{ref_id}",
    "kind": "tool_result",
    "title": f"{tool_name} 输出 ({len(serialized)} bytes)",
    "payload": {
      "ref": pointer["ref"],
      "path": str(path),
      "preview": preview,
      "summary": pointer["summary"],
      "tool": tool_name,
      "size_bytes": len(serialized),
    },
    "sourceTool": tool_name,
    "createdAt": int(time.time()),
  }
  return pointer, artifact


def read_externalized(ref: str) -> dict[str, Any]:
  """Load externalized result by ref id (toolresult://...)."""
  ref_id = str(ref or "").replace("toolresult://", "").strip()
  if not ref_id:
    return {"ok": False, "error": "Invalid ref"}
  base = workspace_path("tool_results")
  if not base.is_dir():
    return {"ok": False, "error": "No externalized results directory"}
  matches = list(base.rglob(f"*_{ref_id}.json"))
  if not matches:
    return {"ok": False, "error": f"Not found: {ref_id}"}
  try:
    data = json.loads(matches[0].read_text(encoding="utf-8"))
    return {"ok": True, "ref": ref, "path": str(matches[0]), "data": data}
  except (OSError, json.JSONDecodeError) as e:
    return {"ok": False, "error": str(e)}


# --- Spill waterfall (dsh spill-policy port) ---
#
# Mirrors `E:\\deepseek-harness\\packages\\spill\\spill-policy\\src\\index.ts`:
# the model-facing post-execute arm saves the FULL plain-text result to a
# session-scoped spill file and replaces the context copy with a bounded
# head/tail preview plus a spill notice. Best-effort: any failure (no session,
# save error, notice over cap) keeps the original inline content.

_SPILL_NOTICE_TEMPLATE = (
  "({omitted} Full formatted result stored at: {locator}. {hint})"
)


def _omitted_label(omitted_bytes: int) -> str:
  if omitted_bytes >= 1024 * 1024:
    return f"{omitted_bytes / 1024 / 1024:.1f} MiB omitted"
  if omitted_bytes >= 1024:
    return f"{omitted_bytes / 1024:.1f} KiB omitted"
  return f"{omitted_bytes} bytes omitted"


def _spill_notice(omitted_bytes: int, locator: str, hint: str) -> str:
  return _SPILL_NOTICE_TEMPLATE.format(
    omitted=_omitted_label(omitted_bytes),
    locator=locator,
    hint=hint,
  )


def spill_text_if_needed(
  text: str,
  *,
  session_id: str = "",
  tool_name: str = "",
  call_id: str = "",
  max_bytes: int | None = None,
  params: Any = None,
  kind: str = "result",
) -> tuple[str | None, dict[str, Any] | None]:
  """Spill `text` and return (bounded_replacement, ref) or (None, None).

  Port of dsh ``spillReplacement``. ``kind`` records which arm produced the
  spill — ``result`` (model-facing post-execute) or ``dispatch`` (session-log
  copy of a sub-call result) — so artifacts are distinguishable on replay.
  Returns ``None`` (keep original) when: no session owner, save fails, or the
  notice itself exceeds the cap.
  """
  if not externalize_enabled(params):
    return None, None
  cap = max_bytes if max_bytes is not None else threshold_bytes(params)
  total = len(text.encode("utf-8"))
  if total <= cap:
    return None, None
  if not session_id:
    return None, None

  ref_id = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
  path = _results_dir(session_id) / f"{tool_name or 'tool'}_{ref_id}.txt"
  try:
    path.write_text(text, encoding="utf-8")
  except OSError:
    return None, None

  locator = str(path)
  hint = "Use read_file on this path for the complete data."
  ref = {
    "ref": f"toolresult://{ref_id}",
    "path": locator,
    "tool": tool_name,
    "call_id": call_id,
    "kind": kind if kind in ("result", "dispatch") else "result",
    "size_bytes": total,
    "hint": hint,
  }

  # Reserve the notice's byte cost INSIDE the cap so the replacement never
  # exceeds it. Worst-case omitted count bounds the real one.
  reserve = len(_spill_notice(total, locator, hint).encode("utf-8")) + 2  # \n\n
  budget = max(0, cap - reserve)
  from ai.core.tools.pipeline import truncate_content_head_tail
  preview_text = truncate_content_head_tail(text, budget, notice="")
  omitted = total - len(preview_text.encode("utf-8"))
  notice = _spill_notice(omitted, locator, hint)
  replaced = f"{preview_text}\n\n{notice}" if preview_text else notice
  if len(replaced.encode("utf-8")) > cap:
    # Invariant: never emit a replacement larger than the cap. The already
    # written spill file is a harmless orphan; cleanup is deferred.
    return None, None
  return replaced, ref
