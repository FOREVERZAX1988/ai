"""ModelManager — list/select NN bundles (Settings → Models)."""

from __future__ import annotations

import json
from typing import Any

from openpilot.common.params import Params

from ai.tools.diagnostics_tools import diff_params


def _bundle_summary(bundle: Any) -> dict[str, Any]:
  ref = getattr(bundle, "ref", None) or getattr(bundle, "internalName", "")
  return {
    "ref": ref,
    "index": int(getattr(bundle, "index", -1)),
    "display_name": getattr(bundle, "displayName", ref),
    "internal_name": getattr(bundle, "internalName", ""),
    "generation": int(getattr(bundle, "generation", 0)),
    "environment": getattr(bundle, "environment", ""),
    "is_20hz": bool(getattr(bundle, "is20hz", False)),
    "runner": str(getattr(getattr(bundle, "runner", None), "raw", getattr(bundle, "runner", ""))),
  }


def _active_bundle_summary(params: Params) -> dict[str, Any] | None:
  try:
    from openpilot.sunnypilot.models.helpers import get_active_bundle

    bundle = get_active_bundle(params)
    if bundle is None:
      return None
    return _bundle_summary(bundle)
  except Exception:
    raw = params.get("ModelManager_ActiveBundle")
    if not raw:
      return None
    if isinstance(raw, bytes):
      raw = json.loads(raw.decode(errors="replace"))
  return {"ref": raw.get("ref"), "display_name": raw.get("displayName"), "raw": True}


def _available_bundles(params: Params):
  """The active source's bundles.

  ModelFetcher has no get_available_bundles(); every caller used to raise and swallow it.
  """
  from openpilot.sunnypilot.models.fetcher import ModelFetcher
  from openpilot.selfdrive.modeld.helpers import chestnut_present
  fetcher = ModelFetcher(params)
  return fetcher.get_bundles_for_source(ModelFetcher.active_source(chestnut_present()))


def list_model_bundles(params: Params | None = None, *, refresh: bool = False) -> dict[str, Any]:
  """List available driving model bundles from ModelManager cache."""
  params = params or Params()
  if refresh:
    params.put("ModelManager_LastSyncTime", 0)

  try:
    bundles = _available_bundles(params)
    items = [_bundle_summary(b) for b in bundles]
    folders: dict[str, list[str]] = {}
    for b in bundles:
      folder = ""
      for ov in getattr(b, "overrides", []) or []:
        if getattr(ov, "key", None) == "folder":
          folder = getattr(ov, "value", "") or ""
          break
      folders.setdefault(folder or "(default)", []).append(getattr(b, "ref", "") or getattr(b, "internalName", ""))

    favs_raw = params.get("ModelManager_Favs")
    if isinstance(favs_raw, bytes):
      favs_raw = favs_raw.decode(errors="replace")
    if isinstance(favs_raw, str):
      favs = [x for x in favs_raw.split(";") if x]
    elif isinstance(favs_raw, list):
      favs = favs_raw
    else:
      favs = []

    return {
      "ok": True,
      "count": len(items),
      "bundles": items,
      "folders": folders,
      "favorites": favs,
      "active": _active_bundle_summary(params),
      "default_ref": "Default",
      "hint": "Use select_model_bundle(ref, confirm=true) while stationary. ref=Default restores stock model.",
    }
  except Exception as e:
    return {"ok": False, "error": str(e), "hint": "ModelManager may be unavailable on this build."}


def get_model_manager_status(params: Params | None = None) -> dict[str, Any]:
  """Active bundle, queued download ref, cache sync, and progress params."""
  params = params or Params()
  download_ref = params.get("ModelManager_DownloadRef")
  if isinstance(download_ref, bytes):
    download_ref = download_ref.decode(errors="replace")

  out: dict[str, Any] = {
    "ok": True,
    "active": _active_bundle_summary(params),
    "download_ref": download_ref,
    "downloading": bool(download_ref),
    "last_sync_ns": params.get("ModelManager_LastSyncTime"),
    "cache_present": bool(params.get("ModelManager_ModelsCache")),
    "clear_cache_pending": bool(params.get_bool("ModelManager_ClearCache")),
    "favorites": params.get("ModelManager_Favs"),
    "runner_cache": params.get("ModelRunnerTypeCache"),
  }

  try:
    bundles = _available_bundles(params)
    if download_ref:
      for b in bundles:
        if getattr(b, "ref", None) == download_ref:
          out["selected_bundle"] = _bundle_summary(b)
          break
  except Exception:
    pass

  return out


def preview_model_bundle_change(params: Params, ref: str) -> dict[str, Any]:
  ref = str(ref or "").strip()
  if ref in ("", "Default", "default", "stock"):
    if not params.get("ModelManager_ActiveBundle"):
      return {"ok": True, "changes": {}, "change_count": 0}
    return {
      "ok": True,
      "changes": {"ModelManager_ActiveBundle": {"before": "set", "after": None}},
      "change_count": 1,
    }

  try:
    bundles = _available_bundles(params)
    match = next((b for b in bundles if getattr(b, "ref", None) == ref or getattr(b, "internalName", None) == ref), None)
    if match is None:
      return {"ok": False, "error": f"unknown model ref: {ref}"}
    return diff_params(params, {"ModelManager_DownloadRef": getattr(match, "ref", ref)})
  except Exception as e:
    return {"ok": False, "error": str(e)}


def select_model_bundle(params: Params, ref: str) -> dict[str, Any]:
  """Select NN model bundle by ref (Default = stock). Queues ModelManager_DownloadRef."""
  ref = str(ref or "").strip()
  if ref in ("", "Default", "default", "stock"):
    had = bool(params.get("ModelManager_ActiveBundle") or params.get("ModelManager_ActiveBundleChestnut"))
    params.remove("ModelManager_ActiveBundle")
    params.remove("ModelManager_ActiveBundleChestnut")
    params.remove("ModelManager_DownloadRef")
    return {"ok": True, "mode": "default", "cleared_active": had}

  try:
    bundles = _available_bundles(params)
    match = next(
      (b for b in bundles if getattr(b, "ref", None) == ref or getattr(b, "internalName", None) == ref),
      None,
    )
    if match is None:
      return {"ok": False, "error": f"unknown model ref: {ref}"}
    params.put("ModelManager_DownloadRef", getattr(match, "ref", ref))
    return {
      "ok": True,
      "ref": getattr(match, "ref", ref),
      "display_name": getattr(match, "displayName", ref),
      "index": int(match.index),
      "hint": "Download runs in background via modeld. Use get_model_manager_status to monitor.",
    }
  except Exception as e:
    return {"ok": False, "error": str(e)}


def refresh_model_list(params: Params) -> dict[str, Any]:
  params.put("ModelManager_LastSyncTime", 0)
  params.put("ModelManager_LastSyncTime_Chestnut", 0)
  return list_model_bundles(params, refresh=False)


def cancel_model_download(params: Params) -> dict[str, Any]:
  had = params.get("ModelManager_DownloadRef") is not None
  params.remove("ModelManager_DownloadRef")
  return {"ok": True, "cancelled": had}


def clear_model_cache(params: Params) -> dict[str, Any]:
  params.put_bool("ModelManager_ClearCache", True)
  return {"ok": True, "hint": "Cache clear runs on next manager cycle; active model is kept."}


def _parse_favs(params: Params) -> list[str]:
  raw = params.get("ModelManager_Favs")
  if isinstance(raw, bytes):
    raw = raw.decode(errors="replace")
  if not raw:
    return []
  if isinstance(raw, str):
    return [x.strip() for x in raw.split(";") if x.strip()]
  if isinstance(raw, list):
    return [str(x).strip() for x in raw if str(x).strip()]
  return []


def manage_model_favorites(
  params: Params,
  *,
  add: list[str] | None = None,
  remove: list[str] | None = None,
  replace: list[str] | None = None,
) -> dict[str, Any]:
  """Manage ModelManager_Favs (semicolon-separated refs, same as UI)."""
  favs = set(_parse_favs(params))
  if replace is not None:
    favs = {str(x).strip() for x in replace if str(x).strip()}
  else:
    for ref in add or []:
      ref = str(ref).strip()
      if ref:
        favs.add(ref)
    for ref in remove or []:
      favs.discard(str(ref).strip())
  ordered = sorted(favs)
  if ordered:
    params.put("ModelManager_Favs", ";".join(ordered))
  else:
    try:
      params.remove("ModelManager_Favs")
    except Exception:
      pass
  return {"ok": True, "favorites": ordered}
