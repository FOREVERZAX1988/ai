"""Provider accounts, model pool, and chat routing (ClawPanel-style model hub)."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from openpilot.common.params import Params

from ai.client import AIConfig, load_config_from_params
from ai.common.storage import read_param, write_param
from ai.model_router import FALLBACKS_PARAM, load_fallback_entries, save_fallback_entries

HUB_PARAM = "ai_model_hub"
OPTIONAL_BASE_URL_PROVIDERS = frozenset({"qwen", "minimax", "mimo", "bigmodel"})
MAX_MODELS_PER_ACCOUNT = 256


def _trim_account_models(models: list[str], *, prefer: set[str] | None = None) -> list[str]:
  """Cap model pool size to limit config.json growth (OpenRouter can return thousands)."""
  prefer = {str(m).strip() for m in (prefer or set()) if str(m).strip()}
  ordered: list[str] = []
  seen: set[str] = set()
  for mid in models:
    if mid in prefer and mid not in seen:
      ordered.append(mid)
      seen.add(mid)
  for mid in models:
    if mid in seen:
      continue
    if len(ordered) >= MAX_MODELS_PER_ACCOUNT:
      break
    ordered.append(mid)
    seen.add(mid)
  return ordered


def _preferred_models_for_account(hub: dict[str, Any], account_id: str) -> set[str]:
  prefer: set[str] = set()
  primary = hub.get("primary") if isinstance(hub.get("primary"), dict) else None
  if primary and str(primary.get("accountId") or "") == account_id:
    model = str(primary.get("model") or "").strip()
    if model:
      prefer.add(model)
  for item in hub.get("fallbacks") or []:
    if not isinstance(item, dict):
      continue
    if str(item.get("accountId") or "") != account_id:
      continue
    model = str(item.get("model") or "").strip()
    if model:
      prefer.add(model)
  return prefer


def _new_account_id() -> str:
  return f"acc_{uuid.uuid4().hex[:10]}"


def _mask_key(key: str) -> str:
  if not key:
    return ""
  if len(key) <= 8:
    return "••••"
  return f"••••{key[-4:]}"


def _provider_label(provider: str) -> str:
  labels = {
    "opencode-zen": "OpenCode Zen",
    "opencode-go": "OpenCode Go",
    "deepseek": "DeepSeek",
    "bigmodel": "智谱 BigModel",
    "qwen": "通义千问",
    "mimo": "小米 MiMo",
    "minimax": "MiniMax",
    "openrouter": "OpenRouter",
    "openai": "OpenAI",
    "kimi": "Kimi",
    "siliconflow": "硅基流动",
    "custom": "Custom",
  }
  return labels.get(provider, provider)


def _sanitize_account(item: dict[str, Any], *, existing: dict[str, Any] | None = None) -> dict[str, Any] | None:
  if not isinstance(item, dict):
    return None
  provider = str(item.get("provider") or "").strip()
  if not provider:
    return None
  acc_id = str(item.get("id") or (existing or {}).get("id") or _new_account_id()).strip()
  label = str(item.get("label") or (existing or {}).get("label") or _provider_label(provider)).strip()[:64]
  api_key = str(item.get("apiKey") or item.get("api_key") or "").strip()
  if api_key.startswith("•") and existing:
    api_key = str(existing.get("apiKey") or existing.get("api_key") or "")
  base_url = str(item.get("baseUrl") or item.get("base_url") or "").strip()
  models_in = item.get("models")
  models: list[str] = []
  if isinstance(models_in, list):
    models = [str(m).strip() for m in models_in if str(m).strip()]
  elif existing and isinstance(existing.get("models"), list):
    models = [str(m).strip() for m in existing.get("models") if str(m).strip()]
  out: dict[str, Any] = {
    "id": acc_id,
    "provider": provider,
    "label": label,
    "apiKey": api_key,
    "baseUrl": base_url,
    "enabled": item.get("enabled", (existing or {}).get("enabled", True)) is not False,
    "models": models,
  }
  fetched = item.get("modelsFetchedAt")
  if fetched is None and existing:
    fetched = existing.get("modelsFetchedAt")
  if fetched is not None:
    try:
      out["modelsFetchedAt"] = int(fetched)
    except (TypeError, ValueError):
      pass
  return out


def _empty_hub() -> dict[str, Any]:
  return {"version": 1, "accounts": [], "primary": None, "fallbacks": []}


def _hub_from_legacy(params: Params) -> dict[str, Any]:
  base = load_config_from_params(params)
  acc_id = "acc_default"
  account = {
    "id": acc_id,
    "provider": base.provider,
    "label": _provider_label(base.provider),
    "apiKey": base.api_key,
    "baseUrl": base.base_url,
    "enabled": True,
    "models": [base.model] if base.model else [],
  }
  accounts = [account]
  fallbacks: list[dict[str, Any]] = []
  account_index = {(base.provider, base.api_key, base.base_url): acc_id}

  def _get_or_create_account(provider: str, api_key: str, base_url: str) -> str:
    key = (provider, api_key, base_url)
    if key in account_index:
      return account_index[key]
    new_id = _new_account_id()
    accounts.append({
      "id": new_id,
      "provider": provider,
      "label": _provider_label(provider),
      "apiKey": api_key,
      "baseUrl": base_url,
      "enabled": True,
      "models": [],
    })
    account_index[key] = new_id
    return new_id

  for fb in load_fallback_entries(params):
    fb_provider = str(fb.get("provider") or base.provider).strip()
    fb_key = str(fb.get("apiKey") or fb.get("api_key") or base.api_key).strip()
    fb_url = str(fb.get("baseUrl") or fb.get("base_url") or base.base_url).strip()
    fb_model = str(fb.get("model") or "").strip()
    if not fb_model:
      continue
    aid = _get_or_create_account(fb_provider, fb_key, fb_url)
    for acc in accounts:
      if acc["id"] == aid and fb_model not in acc["models"]:
        acc["models"].append(fb_model)
    row: dict[str, Any] = {"accountId": aid, "model": fb_model}
    label = str(fb.get("label") or "").strip()
    if label:
      row["label"] = label[:64]
    fallbacks.append(row)

  return {
    "version": 1,
    "accounts": accounts,
    "primary": {"accountId": acc_id, "model": base.model},
    "fallbacks": fallbacks,
  }


def _ensure_hub_primary(params: Params, hub: dict[str, Any]) -> dict[str, Any]:
  """Fill primary routing from legacy params when hub accounts exist but primary is missing."""
  accounts = hub.get("accounts") or []
  if not accounts:
    return hub
  primary = hub.get("primary") if isinstance(hub.get("primary"), dict) else None
  aid = str((primary or {}).get("accountId") or (primary or {}).get("account_id") or "").strip()
  model = str((primary or {}).get("model") or "").strip()
  if aid and model and _account_map(hub).get(aid):
    return hub
  base = load_config_from_params(params)
  if not aid:
    aid = str(accounts[0].get("id") or "acc_default")
  acc = _account_map(hub).get(aid) or accounts[0]
  aid = str(acc.get("id") or aid)
  if not model:
    model = base.model or (acc.get("models") or [""])[0]
  if not model:
    return hub
  out = dict(hub)
  out["primary"] = {"accountId": aid, "model": str(model).strip()}
  models = list(acc.get("models") or [])
  if out["primary"]["model"] and out["primary"]["model"] not in models:
    acc = dict(acc)
    acc["models"] = [out["primary"]["model"], *models]
    out["accounts"] = [
      acc if str(a.get("id")) == aid else a for a in accounts
    ]
  return out


def _persist_model_hub(params: Params, hub: dict[str, Any]) -> None:
  if not hub.get("accounts"):
    return
  write_param(params, HUB_PARAM, json.dumps(hub, ensure_ascii=False))
  _sync_legacy_params(params, hub)


def load_model_hub(params: Params | None = None) -> dict[str, Any]:
  params = params or Params()
  raw = read_param(params, HUB_PARAM)
  migrated = False
  if not raw:
    hub = _hub_from_legacy(params)
    migrated = True
  else:
    try:
      if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
      data = json.loads(raw)
    except Exception:
      hub = _hub_from_legacy(params)
      migrated = True
    else:
      if not isinstance(data, dict):
        hub = _hub_from_legacy(params)
        migrated = True
      else:
        accounts_in = data.get("accounts")
        if not isinstance(accounts_in, list) or not accounts_in:
          hub = _hub_from_legacy(params)
          migrated = True
        else:
          accounts = []
          for item in accounts_in:
            acc = _sanitize_account(item)
            if acc:
              accounts.append(acc)
          if not accounts:
            hub = _hub_from_legacy(params)
            migrated = True
          else:
            primary_in = data.get("primary") if isinstance(data.get("primary"), dict) else None
            primary = _sanitize_route(primary_in) if primary_in else None
            fallbacks = []
            for item in data.get("fallbacks") or []:
              if not isinstance(item, dict):
                continue
              row = _sanitize_route(item)
              if row:
                fallbacks.append(row)
            hub = {
              "version": 1,
              "accounts": accounts,
              "primary": primary,
              "fallbacks": fallbacks,
            }
  hub = _ensure_hub_primary(params, hub)
  if migrated:
    try:
      _persist_model_hub(params, hub)
    except Exception:
      pass
  return hub


def hub_for_api(params: Params | None = None, *, mask_keys: bool = False) -> dict[str, Any]:
  hub = load_model_hub(params)
  accounts = []
  for acc in hub.get("accounts") or []:
    row = dict(acc)
    if mask_keys and row.get("apiKey"):
      row["apiKey"] = _mask_key(str(row["apiKey"]))
    accounts.append(row)
  return {
    "version": hub.get("version", 1),
    "accounts": accounts,
    "primary": hub.get("primary"),
    "fallbacks": hub.get("fallbacks") or [],
  }


def _account_map(hub: dict[str, Any]) -> dict[str, dict[str, Any]]:
  return {str(a.get("id")): a for a in hub.get("accounts") or [] if a.get("id")}


def route_to_config(
  account: dict[str, Any],
  route: dict[str, Any],
  *,
  base: AIConfig | None = None,
) -> AIConfig:
  base = base or AIConfig(provider="opencode-zen", model="", api_key="")
  model = str(route.get("model") or "").strip()
  cfg = account_to_config(account, model, base=base)
  try:
    mt = int(route.get("maxTokens") or 0)
    if mt > 0:
      cfg.max_tokens = mt
  except (TypeError, ValueError):
    pass
  for attr, key in (("temperature", "temperature"), ("top_p", "topP")):
    raw = route.get(key)
    if raw is None or str(raw).strip() == "":
      continue
    try:
      setattr(cfg, attr, float(raw))
    except (TypeError, ValueError):
      pass
  if "thinkingEnabled" in route or "thinking_enabled" in route:
    raw_think = route.get("thinkingEnabled", route.get("thinking_enabled"))
    cfg.thinking_enabled = raw_think is not False and str(raw_think).lower() not in ("0", "false", "no", "off")
  return cfg


def _sanitize_route(item: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any] | None:
  if not isinstance(item, dict):
    return None
  prev = existing if isinstance(existing, dict) else {}
  aid = str(item.get("accountId") or item.get("account_id") or prev.get("accountId") or "").strip()
  model = str(item.get("model") or prev.get("model") or "").strip()
  if not aid or not model:
    return None
  row: dict[str, Any] = {"accountId": aid, "model": model}
  label = str(item.get("label") or prev.get("label") or "").strip()
  if label:
    row["label"] = label[:64]
  try:
    row["contextWindow"] = max(0, int(item.get("contextWindow", prev.get("contextWindow", 0)) or 0))
  except (TypeError, ValueError):
    row["contextWindow"] = 0
  for key in ("maxTokens",):
    raw = item.get(key, prev.get(key))
    if raw is not None and str(raw).strip() != "":
      try:
        val = int(raw)
        if val > 0:
          row[key] = val
      except (TypeError, ValueError):
        pass
  for key in ("temperature", "topP"):
    raw = item.get(key, prev.get(key))
    if raw is not None and str(raw).strip() != "":
      try:
        row[key] = float(raw)
      except (TypeError, ValueError):
        pass
  if "thinkingEnabled" in item or "thinking_enabled" in item:
    raw_think = item.get("thinkingEnabled", item.get("thinking_enabled"))
    row["thinkingEnabled"] = raw_think is not False and str(raw_think).lower() not in ("0", "false", "no", "off")
  elif "thinkingEnabled" in prev or "thinking_enabled" in prev:
    raw_think = prev.get("thinkingEnabled", prev.get("thinking_enabled"))
    row["thinkingEnabled"] = raw_think is not False and str(raw_think).lower() not in ("0", "false", "no", "off")
  return row


def route_context_window(route: dict[str, Any] | None, *, model: str = "") -> int:
  from ai.common.context_config import context_window_for_model
  if isinstance(route, dict):
    try:
      override = int(route.get("contextWindow") or 0)
      if override > 0:
        return override
    except (TypeError, ValueError):
      pass
  return context_window_for_model(model)


def account_to_config(account: dict[str, Any], model: str, *, base: AIConfig | None = None) -> AIConfig:
  base = base or AIConfig(provider="opencode-zen", model="", api_key="")
  return AIConfig(
    provider=str(account.get("provider") or base.provider),
    model=str(model or "").strip(),
    api_key=str(account.get("apiKey") or account.get("api_key") or ""),
    base_url=str(account.get("baseUrl") or account.get("base_url") or ""),
    system_prompt=base.system_prompt,
    temperature=base.temperature,
    top_p=base.top_p,
    max_tokens=base.max_tokens,
    thinking_enabled=base.thinking_enabled,
    thinking_keep=base.thinking_keep,
  )


def resolve_primary_config(params: Params | None = None, base: AIConfig | None = None) -> AIConfig:
  params = params or Params()
  base = base or load_config_from_params(params)
  hub = load_model_hub(params)
  amap = _account_map(hub)
  primary = hub.get("primary") if isinstance(hub.get("primary"), dict) else None
  if primary:
    aid = str(primary.get("accountId") or primary.get("account_id") or "").strip()
    model = str(primary.get("model") or "").strip()
    acc = amap.get(aid)
    if acc and model:
      cfg = route_to_config(acc, primary, base=base)
      if cfg.api_key and cfg.model:
        return cfg
  return base


def resolve_fallback_configs(params: Params | None = None, base: AIConfig | None = None) -> list[AIConfig]:
  params = params or Params()
  base = base or resolve_primary_config(params)
  hub = load_model_hub(params)
  amap = _account_map(hub)
  out: list[AIConfig] = []
  seen: set[tuple[str, str]] = {(base.provider, base.model)}
  for item in hub.get("fallbacks") or []:
    if not isinstance(item, dict):
      continue
    aid = str(item.get("accountId") or item.get("account_id") or "").strip()
    model = str(item.get("model") or "").strip()
    acc = amap.get(aid)
    if not acc or not model:
      continue
    if acc.get("enabled") is False:
      continue
    key = (str(acc.get("provider")), model)
    if key in seen:
      continue
    seen.add(key)
    cfg = route_to_config(acc, item, base=base)
    if not cfg.api_key:
      continue
    if cfg.provider == "custom" and not cfg.base_url:
      continue
    out.append(cfg)
  if out:
    return out
  return _legacy_fallback_configs(params, base)


def _legacy_fallback_configs(params: Params, base: AIConfig) -> list[AIConfig]:
  from ai.model_router import _parse_fallbacks
  return _parse_fallbacks(params, base)


def resolve_chat_chain(params: Params | None = None, base: AIConfig | None = None) -> list[AIConfig]:
  params = params or Params()
  primary = resolve_primary_config(params, base)
  return [primary, *resolve_fallback_configs(params, primary)]


def _sync_legacy_params(params: Params, hub: dict[str, Any]) -> None:
  amap = _account_map(hub)
  primary = hub.get("primary") if isinstance(hub.get("primary"), dict) else None
  if primary:
    aid = str(primary.get("accountId") or "").strip()
    model = str(primary.get("model") or "").strip()
    acc = amap.get(aid)
    if acc and model:
      write_param(params, "ai_provider", str(acc.get("provider") or ""))
      write_param(params, "ai_model", model)
      if acc.get("apiKey"):
        write_param(params, "ai_api_key", str(acc.get("apiKey")))
      write_param(params, "ai_base_url", str(acc.get("baseUrl") or ""))

  legacy_fallbacks = []
  for item in hub.get("fallbacks") or []:
    if not isinstance(item, dict):
      continue
    aid = str(item.get("accountId") or "").strip()
    model = str(item.get("model") or "").strip()
    acc = amap.get(aid)
    if not acc or not model:
      continue
    row: dict[str, Any] = {
      "provider": str(acc.get("provider") or ""),
      "model": model,
    }
    label = str(item.get("label") or "").strip()
    if label:
      row["label"] = label
    if acc.get("apiKey"):
      row["api_key"] = str(acc.get("apiKey"))
    if acc.get("baseUrl"):
      row["base_url"] = str(acc.get("baseUrl"))
    legacy_fallbacks.append(row)
  save_fallback_entries(params, legacy_fallbacks)


def save_model_hub(params: Params, incoming: dict[str, Any]) -> dict[str, Any]:
  existing = load_model_hub(params)
  existing_map = _account_map(existing)
  accounts = []
  for item in incoming.get("accounts") or []:
    if not isinstance(item, dict):
      continue
    acc_id = str(item.get("id") or "").strip()
    prev = existing_map.get(acc_id) if acc_id else None
    acc = _sanitize_account(item, existing=prev)
    if acc:
      accounts.append(acc)
  if not accounts:
    raise ValueError("至少需要一个服务商账户")

  primary_in = incoming.get("primary") if isinstance(incoming.get("primary"), dict) else None
  prev_primary = existing.get("primary") if isinstance(existing.get("primary"), dict) else None
  primary = _sanitize_route(primary_in, existing=prev_primary) if primary_in else None

  fallbacks = []
  prev_fallbacks = existing.get("fallbacks") or []
  prev_by_key = {
    f"{f.get('accountId')}::{f.get('model')}": f
    for f in prev_fallbacks
    if isinstance(f, dict) and f.get("accountId") and f.get("model")
  }
  for item in incoming.get("fallbacks") or []:
    if not isinstance(item, dict):
      continue
    aid = str(item.get("accountId") or item.get("account_id") or "").strip()
    model = str(item.get("model") or "").strip()
    prev = prev_by_key.get(f"{aid}::{model}") if aid and model else None
    row = _sanitize_route(item, existing=prev)
    if row:
      fallbacks.append(row)

  hub = {
    "version": 1,
    "accounts": accounts,
    "primary": primary,
    "fallbacks": fallbacks,
  }
  for acc in hub["accounts"]:
    acc_id = str(acc.get("id") or "")
    acc["models"] = _trim_account_models(
      list(acc.get("models") or []),
      prefer=_preferred_models_for_account(hub, acc_id),
    )
  write_param(params, HUB_PARAM, json.dumps(hub, ensure_ascii=False))
  _sync_legacy_params(params, hub)
  return hub_for_api(params, mask_keys=False)


def update_account_models(
  params: Params,
  account_id: str,
  models: list[str],
) -> dict[str, Any]:
  hub = load_model_hub(params)
  amap = _account_map(hub)
  acc = amap.get(account_id)
  if not acc:
    raise ValueError("account not found")
  prefer = _preferred_models_for_account(hub, account_id)
  acc["models"] = _trim_account_models(
    [str(m).strip() for m in models if str(m).strip()],
    prefer=prefer,
  )
  acc["modelsFetchedAt"] = int(time.time())
  write_param(params, HUB_PARAM, json.dumps(hub, ensure_ascii=False))
  return hub_for_api(params, mask_keys=False)


def account_config_by_id(params: Params, account_id: str) -> AIConfig | None:
  hub = load_model_hub(params)
  acc = _account_map(hub).get(account_id)
  if not acc:
    return None
  model = ""
  primary = hub.get("primary") if isinstance(hub.get("primary"), dict) else None
  if primary and str(primary.get("accountId")) == account_id:
    model = str(primary.get("model") or "")
  if not model and acc.get("models"):
    model = str(acc["models"][0])
  return account_to_config(acc, model)


def provider_needs_base_url(provider: str) -> bool:
  return provider == "custom"


def provider_optional_base_url(provider: str) -> bool:
  return provider in OPTIONAL_BASE_URL_PROVIDERS
