"""HTTP API handlers (extracted from aid.py)."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web

from openpilot.common.swaglog import cloudlog

from ai.model_router import fallbacks_for_api, load_fallback_entries, save_fallback_entries
from ai.model_accounts import (
  account_config_by_id,
  hub_for_api,
  load_model_hub,
  save_model_hub,
  update_account_models,
)
from ai.server.deps import (
  filter_tools,
  get_state_reader,
  get_tool_handlers,
  json_response,
  mask_key,
  openpilot_root,
  params,
  read_ai_config,
  read_param_bool_val,
  read_param_str,
  resolve_max_tool_rounds,
  sse,
)
from ai.client import AIConfig, merge_config_from_body, test_connection, list_models
from ai.common.params import (
  AI_DEFAULT_MODELS,
  AI_EMBEDDING_MODEL_CATALOG,
  AI_EMBEDDING_PROVIDER_LABELS,
  AI_EMBEDDING_PROVIDERS,
  AI_PROVIDER_LABELS,
  AI_PROVIDER_MODEL_CATALOG,
  AI_PROVIDERS,
  AI_SAME_MODE_EMBEDDING_MODELS,
)
from ai.common.storage import write_param, write_param_bool
from ai.embedding import DEFAULT_EMBEDDING_MODELS, load_embedding_config
from ai.persona import ensure_default_persona
from ai.skills.loader import list_skills, load_enabled_skill_ids, save_enabled_skill_ids
from ai.system.admin import is_admin_mode
from ai.system.host_env import get_host_environment
from ai.system.safety import ACTION_RULES, is_action_allowed
from ai.system.shell import run_command
from ai.agents.config import agents_enabled_payload
from ai.agents.office import office_snapshot as get_office_snapshot
from ai.agents.orchestrator import detect_orchestration_plan, run_chat_with_agents
from ai.agents.registry import filter_tools_for_agent, get_agent, list_agents, orchestrator_id
from ai.agents.router import resolve_agent_route
from ai.chat_jobs import cancel_job, cancel_jobs_for_session, get_job, list_active_jobs, start_chat_job, wait_for_job
from ai.command_queue import submit_chat_request
from ai.chat_runner import ChatCancelled
from ai.sync_hub import broadcast_config, broadcast_notifications, broadcast_sessions
from ai.tools.agent_tools import tool_meta_for_host
from ai.tools.memory_store import (
  append_note,
  delete_note,
  get_memory,
  update_vehicle_profile,
  sync_vehicle_profile_from_state,
)
from ai.tools.notifications import list_notifications, mark_notifications_read
from ai.tools.rag_store import (
  list_documents,
  remove_document,
  search_documents,
  upsert_document,
  reindex_all,
)
from ai.tools.scheduler import list_tasks, remove_task, upsert_task
from ai.tools.session_store import get_sessions, save_sessions
from ai.tools.workflows import list_workflows
from ai.tools.consumer_tools import consumer_bootstrap_payload
from ai.tools.write_pending import confirm_pending, list_pending
from ai.usage_log import load_embedding_usage, load_usage

_PARAMS = params()
_get_state_reader = get_state_reader
_json_response = json_response
_sse = sse
_read_param_str = read_param_str
_read_param_bool = read_param_bool_val
_mask_key = mask_key
_read_ai_config = read_ai_config
_get_tool_handlers = get_tool_handlers
_resolve_max_tool_rounds = resolve_max_tool_rounds
_filter_tools = filter_tools


async def _parse_chat_body(request: web.Request) -> tuple[dict[str, Any] | None, AIConfig | None, web.Response | None]:
  config = _read_ai_config()
  if not config.is_configured:
    return None, None, _json_response({
      "ok": False,
      "error": config.configuration_error or "AI not configured. Set provider, model, and API key first.",
    }, status=400)

  try:
    body = await request.json()
  except json.JSONDecodeError:
    return None, None, _json_response({"ok": False, "error": "Invalid JSON body."}, status=400)

  raw_messages = body.get("messages", [])
  if not isinstance(raw_messages, list) or not raw_messages:
    return None, None, _json_response({"ok": False, "error": "messages must be a non-empty list."}, status=400)

  # Owner slash commands: /调手感 → workflow + consumer mode
  try:
    from ai.tools.consumer_wizards import resolve_wizard_by_slash
    last = raw_messages[-1] if raw_messages else {}
    if last.get("role") == "user":
      content = last.get("content", "")
      text = content if isinstance(content, str) else str(content)
      wiz = resolve_wizard_by_slash(text)
      if wiz:
        body.setdefault("consumerMode", True)
        body.setdefault("workflow", wiz.get("workflow_id"))
        if text.strip() in (wiz.get("slash") or []) or len(text.strip().split()) <= 1:
          last["content"] = wiz.get("starter_prompt") or text
  except Exception:
    pass

  return body, config, None


def _prepare_chat_run(body: dict[str, Any]) -> dict[str, Any]:
  tools_enabled = bool(body.get("tools", True))
  tool_prefs = body.get("toolPrefs") or {}
  max_tool_rounds = _resolve_max_tool_rounds(body.get("maxToolRounds"))
  drive_state = _get_state_reader().update(timeout=0)
  try:
    from ai.system.host_env import is_pc_dev
    pc_dev = is_pc_dev()
  except Exception:
    pc_dev = os.name == "nt" or not os.path.isfile("/TICI")

  route = resolve_agent_route(
    body,
    driving=drive_state.is_driving,
    pc_dev=pc_dev,
    params=_PARAMS,
  )
  route_dict = route.to_dict()
  if route.workflow_id and not body.get("workflow"):
    body["workflow"] = route.workflow_id

  from ai.tools.toolsets import resolve_toolset
  toolset_id = resolve_toolset(
    drive_state.is_driving,
    agent_id=route.agent_id,
    explicit=str(body.get("toolset") or body.get("toolsetId") or "").strip(),
  )

  tools = _filter_tools(
    tools_enabled,
    tool_prefs,
    driving=drive_state.is_driving,
    toolset_id=toolset_id,
  ) if tools_enabled else None
  agent = get_agent(route.agent_id)
  if agent and tools:
    tools = filter_tools_for_agent(tools, agent)

  orchestration_plan = None
  if route.agent_id == orchestrator_id() and route.reason == "default":
    plan = detect_orchestration_plan(
      body,
      driving=drive_state.is_driving,
      pc_dev=pc_dev,
      params=_PARAMS,
    )
    if plan:
      orchestration_plan = [p.to_dict() for p in plan]

  return {
    "tools": tools,
    "max_tool_rounds": max_tool_rounds,
    "route": route_dict,
    "orchestration_plan": orchestration_plan,
    "toolset": toolset_id,
  }


def _chat_tools_for_body(body: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, int]:
  prep = _prepare_chat_run(body)
  return prep["tools"], prep["max_tool_rounds"]


async def api_chat(request: web.Request) -> web.Response:
  try:
    body, config, err = await _parse_chat_body(request)
    if err is not None:
      return err
    assert body is not None and config is not None

    prep = _prepare_chat_run(body)
    run_body = {**body, "_config": config, "_agent_route": prep["route"]}
    if prep.get("orchestration_plan"):
      run_body["_orchestration_plan"] = prep["orchestration_plan"]

    async def stream_response():
      response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={"Content-Type": "text/event-stream; charset=utf-8"},
      )
      await response.prepare(request)

      async def emit(event: dict[str, Any]) -> None:
        await response.write(_sse(event))

      try:
        await run_chat_with_agents(
          run_body,
          _PARAMS,
          emit,
          get_state_reader=_get_state_reader,
          get_tool_handlers=_get_tool_handlers,
          tools=prep["tools"],
          max_tool_rounds=prep["max_tool_rounds"],
        )
      except ChatCancelled:
        pass
      await response.write_eof()
      return response

    return await stream_response()
  except Exception as e:
    cloudlog.error(f"aid: api_chat error: {e}")
    return _json_response({"ok": False, "error": f"Internal error: {e}"}, status=500)


async def api_chat_jobs(request: web.Request) -> web.Response:
  """POST: start background job. GET ?sessionId=: list active jobs."""
  if request.method == "GET":
    session_id = str(request.query.get("sessionId", "") or "").strip()
    jobs = list_active_jobs(session_id or None)
    from ai.command_queue import list_queued
    return _json_response({"ok": True, "jobs": jobs, "queue": list_queued(session_id or None)})

  try:
    body, config, err = await _parse_chat_body(request)
    if err is not None:
      return err
    assert body is not None and config is not None

    session_id = str(body.get("sessionId", "") or "").strip()
    prep = _prepare_chat_run(body)
    body = {
      **body,
      "_agent_route": prep["route"],
      **({"_orchestration_plan": prep["orchestration_plan"]} if prep.get("orchestration_plan") else {}),
    }
    queue_mode = str(body.get("queueMode") or body.get("queue_mode") or "steer").strip()
    body["queueMode"] = queue_mode
    drive_state = _get_state_reader().update(timeout=0)

    async def _start(b: dict[str, Any]) -> str:
      return await start_chat_job(
        session_id,
        b,
        _PARAMS,
        get_state_reader=_get_state_reader,
        get_tool_handlers=_get_tool_handlers,
        tools=prep["tools"],
        max_tool_rounds=prep["max_tool_rounds"],
        config=config,
      )

    submit = await submit_chat_request(
      session_id,
      body,
      driving=drive_state.is_driving,
      queue_mode=queue_mode,
      start_fn=_start,
      cancel_session_fn=cancel_jobs_for_session,
    )
    job_id = submit.get("jobId")
    wait = str(request.query.get("wait", "") or body.get("wait", "")).lower() in ("1", "true", "yes")
    timeout_ms = int(request.query.get("timeoutMs") or body.get("timeoutMs") or 60000)
    result: dict[str, Any] = {
      "ok": True,
      "jobId": job_id,
      "sessionId": session_id,
      "runId": job_id,
      "queueMode": submit.get("queueMode"),
      "queued": submit.get("queued", False),
      "queuePosition": submit.get("queuePosition"),
      "action": submit.get("action"),
    }
    if wait and job_id:
      waited = await wait_for_job(job_id, timeout_ms=timeout_ms)
      if waited:
        result["job"] = waited
        result["status"] = waited.get("status")
    return _json_response(result)
  except Exception as e:
    cloudlog.error(f"aid: api_chat_jobs error: {e}")
    return _json_response({"ok": False, "error": f"Internal error: {e}"}, status=500)


async def api_chat_job_detail(request: web.Request) -> web.Response:
  job_id = request.match_info.get("job_id", "")
  if request.method == "DELETE":
    ok = await cancel_job(job_id)
    if not ok:
      return _json_response({"ok": False, "error": "Job not found"}, status=404)
    return _json_response({"ok": True, "cancelled": True})

  since = int(request.query.get("since", "0") or "0")
  job = get_job(job_id, since=since)
  if not job:
    return _json_response({"ok": False, "error": "Job not found"}, status=404)

  wait = str(request.query.get("wait", "")).lower() in ("1", "true", "yes")
  if wait and job.get("status") == "running":
    timeout_ms = int(request.query.get("timeoutMs", "60000") or "60000")
    waited = await wait_for_job(job_id, timeout_ms=timeout_ms)
    if waited:
      job = waited
  return _json_response(job)



async def api_workflows(request: web.Request) -> web.Response:
  return _json_response({"ok": True, "workflows": list_workflows()})


async def api_notifications(request: web.Request) -> web.Response:
  if request.method == "POST":
    mark_notifications_read()
    try:
      await broadcast_notifications()
    except Exception as e:
      cloudlog.warning(f"aid: broadcast_notifications failed: {e}")
    return _json_response({"ok": True})
  unread = request.query.get("unread", "1") != "0"
  return _json_response(list_notifications(unread_only=unread))


async def api_adaptation_bundle(request: web.Request) -> web.Response:
  project_id = request.match_info.get("project_id", "")
  from ai.tools.adaptation import export_adaptation_bundle
  result = export_adaptation_bundle(project_id)
  if not result.get("ok"):
    return _json_response(result, status=404)
  if request.query.get("download") == "1":
    filename = f"adaptation_{project_id}.json"
    return web.Response(
      body=json.dumps(result, ensure_ascii=False, indent=2),
      content_type="application/json",
      headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
  return _json_response(result)


# -----------------------------------------------------------------------------
# Streaming helpers
# -----------------------------------------------------------------------------

def _sse(data: dict[str, Any]) -> bytes:
  return ("data: " + json.dumps(data, ensure_ascii=False, default=str) + "\n\n").encode("utf-8")


# -----------------------------------------------------------------------------
# API handlers
# -----------------------------------------------------------------------------

async def api_bootstrap(request: web.Request) -> web.Response:
  """Single round-trip bootstrap: status + config + providers (faster page load)."""
  try:
    ensure_default_persona(_PARAMS)
    reader = _get_state_reader()
    state = reader.update(timeout=0)
    sync_vehicle_profile_from_state(
      _PARAMS,
      brand=state.brand or "",
      car_fingerprint=state.car_fingerprint or "",
    )
    config = _read_ai_config()
    embed_cfg = load_embedding_config(_PARAMS, config)
    skills_on = load_enabled_skill_ids(_PARAMS)
    from ai.timezone_util import read_ai_timezone_name
    tz_name = read_ai_timezone_name(_PARAMS)
    first_run_done = _read_param_bool("ai_first_run_done")
    try:
      from ai.fork.detect_fork import detect_fork
      fork_detected = detect_fork(openpilot_root())
    except Exception:
      fork_detected = {"ok": False}

    bootstrap_models: list[dict[str, Any]] = [
      {"id": mid} for mid in (AI_PROVIDER_MODEL_CATALOG.get(config.provider) or []) if mid
    ]
    models_source = "catalog"
    if config.is_configured and config.model:
      known = {m.get("id") for m in bootstrap_models}
      if config.model not in known:
        bootstrap_models.insert(0, {"id": config.model})

    return _json_response({
    "ok": True,
    "driving": state.is_driving,
    "state": state.to_dict(),
    "ai": {
      "configured": config.is_configured,
      "provider": config.provider,
      "model": config.model,
      "configureError": config.configuration_error,
    },
    "providers": AI_PROVIDERS,
    "providerLabels": AI_PROVIDER_LABELS,
    "defaults": AI_DEFAULT_MODELS,
    "modelCatalog": AI_PROVIDER_MODEL_CATALOG,
    "models": bootstrap_models,
    "modelsSource": models_source,
    "config": {
      "provider": config.provider,
      "model": config.model,
      "apiKey": _mask_key(config.api_key),
      "baseUrl": config.base_url,
      "systemPrompt": config.system_prompt,
      "temperature": config.temperature,
      "topP": config.top_p,
      "maxTokens": config.max_tokens,
      "thinkingEnabled": config.thinking_enabled,
      "thinkingKeep": config.thinking_keep,
      "timezone": tz_name,
      "configured": config.is_configured,
      "configureError": config.configuration_error,
      "embeddingMode": embed_cfg.mode,
      "embeddingProvider": embed_cfg.provider,
      "embeddingModel": embed_cfg.model,
      "embeddingApiKey": _mask_key(_read_param_str("ai_embedding_api_key")) if embed_cfg.mode == "separate" else "",
      "embeddingBaseUrl": embed_cfg.base_url,
      "embeddingConfigured": embed_cfg.is_configured,
      "modelHub": hub_for_api(_PARAMS),
      "modelFallbacks": fallbacks_for_api(_PARAMS, config),
    },
    "embeddingDefaults": DEFAULT_EMBEDDING_MODELS,
    "embeddingProviders": AI_EMBEDDING_PROVIDERS,
    "embeddingProviderLabels": AI_EMBEDDING_PROVIDER_LABELS,
    "embeddingModelCatalog": AI_EMBEDDING_MODEL_CATALOG,
    "embeddingSameModeCatalog": AI_SAME_MODE_EMBEDDING_MODELS,
    "tools": tool_meta_for_host(),
    "hostEnvironment": get_host_environment(),
    "skills": list_skills(),
    "skillsEnabled": sorted(skills_on) if skills_on is not None else None,
    "adminMode": is_admin_mode(_PARAMS),
    "onboarding": {
      "firstRunDone": first_run_done,
      "showWizard": not config.is_configured,
    },
    "fork": fork_detected if fork_detected.get("ok") else None,
    "workflows": list_workflows(),
    "consumer": consumer_bootstrap_payload(),
    "agents": list_agents(include_orchestrator=True),
    "agentsConfig": agents_enabled_payload(_PARAMS),
    "office": get_office_snapshot(),
    "notifications": list_notifications(unread_only=True).get("notifications", [])[:5],
    })
  except Exception as e:
    cloudlog.error(f"aid: api_bootstrap error: {e}")
    return _json_response({"ok": False, "error": str(e)}, status=500)


async def api_status(request: web.Request) -> web.Response:
  try:
    state = _get_state_reader().update(timeout=0)
    config = _read_ai_config()
  except Exception as e:
    return _json_response({"ok": False, "error": str(e)}, status=500)
  return _json_response({
    "ok": True,
    "driving": state.is_driving,
    "state": state.to_dict(),
    "ai": {
      "configured": config.is_configured,
      "provider": config.provider,
      "model": config.model,
    },
  })


async def api_providers(request: web.Request) -> web.Response:
  return _json_response({
    "ok": True,
    "providers": AI_PROVIDERS,
    "providerLabels": AI_PROVIDER_LABELS,
    "defaults": AI_DEFAULT_MODELS,
    "modelCatalog": AI_PROVIDER_MODEL_CATALOG,
    "embeddingProviders": AI_EMBEDDING_PROVIDERS,
    "embeddingProviderLabels": AI_EMBEDDING_PROVIDER_LABELS,
    "embeddingModelCatalog": AI_EMBEDDING_MODEL_CATALOG,
    "embeddingSameModeCatalog": AI_SAME_MODE_EMBEDDING_MODELS,
    "embeddingDefaults": DEFAULT_EMBEDDING_MODELS,
    "rules": {k: {"category": v.category.value, "description": v.description}
              for k, v in ACTION_RULES.items()},
  })


async def api_get_config(request: web.Request) -> web.Response:
  from ai.common.context_config import compaction_settings
  from ai.common.evolution_config import evolution_settings
  from ai.model_accounts import load_model_hub, route_context_window
  from ai.timezone_util import read_ai_timezone_name

  config = _read_ai_config()
  embed_cfg = load_embedding_config(_PARAMS, config)
  hub = load_model_hub(_PARAMS)
  primary_route = hub.get("primary") if isinstance(hub.get("primary"), dict) else {}
  route_cw = 0
  try:
    route_cw = int(primary_route.get("contextWindow") or 0)
  except (TypeError, ValueError):
    route_cw = 0
  ctx = compaction_settings(model=config.model, context_window=route_cw)
  evo = evolution_settings()
  return _json_response({
    "ok": True,
    "config": {
      "provider": config.provider,
      "model": config.model,
      "apiKey": _mask_key(config.api_key),
      "baseUrl": config.base_url,
      "modelFallbacks": fallbacks_for_api(_PARAMS, config),
      "modelHub": hub_for_api(_PARAMS),
      "systemPrompt": config.system_prompt,
      "temperature": config.temperature,
      "topP": config.top_p,
      "maxTokens": config.max_tokens,
      "thinkingEnabled": config.thinking_enabled,
      "thinkingKeep": config.thinking_keep,
      "timezone": read_ai_timezone_name(_PARAMS),
      "configured": config.is_configured,
      "configureError": config.configuration_error,
      "embeddingMode": embed_cfg.mode,
      "embeddingProvider": embed_cfg.provider,
      "embeddingModel": embed_cfg.model,
      "embeddingApiKey": _mask_key(_read_param_str("ai_embedding_api_key")) if embed_cfg.mode == "separate" else "",
      "embeddingBaseUrl": embed_cfg.base_url,
      "embeddingConfigured": embed_cfg.is_configured,
      "contextWindow": ctx.get("contextWindow"),
      "compactionEnabled": ctx.get("enabled"),
      "compactAfterTurns": ctx.get("compactAfterTurns"),
      "keepRecentTurns": ctx.get("keepRecentTurns"),
      "reserveTokens": ctx.get("reserveTokens"),
      "compactionTokenTrigger": ctx.get("tokenTrigger"),
      "compactThresholdTokens": ctx.get("compactThresholdTokens"),
      "evolutionEnabled": evo.get("enabled"),
      "evolutionAutoPropose": evo.get("autoPropose"),
      "evolutionAutoWorkspace": evo.get("autoWorkspace"),
      "evolutionAutoMemory": evo.get("autoMemory"),
      "evolutionLlmReflect": evo.get("llmReflect"),
      "evolutionToolDesc": evo.get("toolDescEvolution"),
      "skillsDisclosureMax": evo.get("skillsDisclosureMax"),
      "evolutionCandidates": evo.get("evolutionCandidates"),
      "evolutionGepaEnabled": evo.get("gepaEnabled"),
      "evolutionGepaIterations": evo.get("gepaIterations"),
      "evolutionEvalCases": evo.get("evalCases"),
      "evolutionUseDspy": evo.get("useDspy"),
    },
  })


async def api_post_config(request: web.Request) -> web.Response:
  state = _get_state_reader().update(timeout=0)
  allowed, reason = is_action_allowed("write_ai_config", state, admin=is_admin_mode(_PARAMS))
  if not allowed:
    return _json_response({"ok": False, "error": reason}, status=403)

  try:
    body = await request.json()
  except json.JSONDecodeError:
    return _json_response({"ok": False, "error": "Invalid JSON body."}, status=400)

  def _put(key: str, value: Any) -> None:
    if value is None:
      return
    if isinstance(value, bool):
      write_param_bool(_PARAMS, key, value)
    else:
      write_param(_PARAMS, key, str(value))

  try:
    _put("ai_provider", body.get("provider"))
    _put("ai_model", body.get("model"))
    api_key = body.get("apiKey", "")
    if api_key and not str(api_key).startswith("•"):
      _put("ai_api_key", str(api_key).strip())
    _put("ai_base_url", body.get("baseUrl"))
    _put("ai_system_prompt", body.get("systemPrompt"))
    _put("ai_temperature", body.get("temperature"))
    _put("ai_top_p", body.get("topP"))
    _put("ai_max_tokens", body.get("maxTokens"))
    _put("ai_context_window", body.get("contextWindow"))
    _put("ai_compaction_enabled", body.get("compactionEnabled"))
    _put("ai_compact_after_turns", body.get("compactAfterTurns"))
    _put("ai_keep_recent_turns", body.get("keepRecentTurns"))
    _put("ai_reserve_tokens", body.get("reserveTokens"))
    _put("ai_compaction_token_trigger", body.get("compactionTokenTrigger"))
    _put("ai_evolution_enabled", body.get("evolutionEnabled"))
    _put("ai_evolution_auto_propose", body.get("evolutionAutoPropose"))
    _put("ai_evolution_auto_workspace", body.get("evolutionAutoWorkspace"))
    _put("ai_evolution_auto_memory", body.get("evolutionAutoMemory"))
    _put("ai_evolution_llm_reflect", body.get("evolutionLlmReflect"))
    _put("ai_evolution_tool_desc", body.get("evolutionToolDesc"))
    _put("ai_skills_disclosure_max", body.get("skillsDisclosureMax"))
    _put("ai_evolution_candidates", body.get("evolutionCandidates"))
    _put("ai_evolution_gepa_enabled", body.get("evolutionGepaEnabled"))
    _put("ai_evolution_gepa_iterations", body.get("evolutionGepaIterations"))
    _put("ai_evolution_eval_cases", body.get("evolutionEvalCases"))
    _put("ai_evolution_use_dspy", body.get("evolutionUseDspy"))
    _put("ai_thinking_enabled", body.get("thinkingEnabled"))
    _put("ai_thinking_keep", body.get("thinkingKeep"))
    _put("ai_embedding_mode", body.get("embeddingMode"))
    _put("ai_embedding_provider", body.get("embeddingProvider"))
    _put("ai_embedding_model", body.get("embeddingModel"))
    emb_key = body.get("embeddingApiKey", "")
    if emb_key and not str(emb_key).startswith("•"):
      _put("ai_embedding_api_key", emb_key)
    _put("ai_embedding_base_url", body.get("embeddingBaseUrl"))
    tz = body.get("timezone")
    if tz is not None and str(tz).strip():
      _put("ai_timezone", str(tz).strip())
    if "modelHub" in body and isinstance(body.get("modelHub"), dict):
      save_model_hub(_PARAMS, body["modelHub"])
    elif "modelFallbacks" in body:
      existing = load_fallback_entries(_PARAMS)
      incoming = body.get("modelFallbacks") or []
      merged: list[dict[str, Any]] = []
      for i, row in enumerate(incoming):
        if not isinstance(row, dict):
          continue
        item = dict(row)
        api_key = str(item.get("apiKey") or item.get("api_key") or "").strip()
        if api_key.startswith("•") and i < len(existing):
          item["apiKey"] = existing[i].get("apiKey") or existing[i].get("api_key") or ""
        merged.append(item)
      save_fallback_entries(_PARAMS, merged)
  except Exception as e:
    cloudlog.error(f"aid: api_post_config failed: {e}")
    return _json_response({"ok": False, "error": str(e)}, status=500)

  config = _read_ai_config()
  try:
    await broadcast_config(_PARAMS)
  except Exception as e:
    cloudlog.warning(f"aid: broadcast_config failed: {e}")
  return _json_response({
    "ok": True,
    "configured": config.is_configured,
    "configureError": config.configuration_error,
    "modelHub": hub_for_api(_PARAMS),
  })


async def api_models(request: web.Request) -> web.Response:
  try:
    saved = _read_ai_config()
    body = None
    if request.method == "POST":
      try:
        body = await request.json()
      except json.JSONDecodeError:
        return _json_response({"ok": False, "error": "Invalid JSON body."}, status=400)
    account_id = ""
    if body:
      account_id = str(body.get("accountId") or body.get("account_id") or "").strip()
    if account_id:
      config = account_config_by_id(_PARAMS, account_id)
      if not config:
        return _json_response({"ok": False, "error": "账户不存在"}, status=404)
    else:
      config = merge_config_from_body(saved, body)
    result = await list_models(config)
    models = result.get("models") or []
    if account_id and result.get("ok") and models:
      ids = [str(m.get("id") if isinstance(m, dict) else m) for m in models]
      ids = [m for m in ids if m]
      if ids:
        update_account_models(_PARAMS, account_id, ids)
    payload: dict[str, Any] = {
      "ok": bool(result.get("ok")),
      "error": result.get("error"),
      "models": models,
      "configured": config.is_configured,
      "configureError": config.configuration_error,
      "source": result.get("source"),
    }
    if account_id:
      payload["modelHub"] = hub_for_api(_PARAMS)
    return _json_response(payload)
  except Exception as e:
    cloudlog.error(f"aid: api_models error: {e}")
    return _json_response({"ok": False, "error": f"Internal error: {e}", "models": []}, status=500)


async def api_test_connection(request: web.Request) -> web.Response:
  try:
    saved = _read_ai_config()
    body = None
    if request.method == "POST":
      try:
        body = await request.json()
      except json.JSONDecodeError:
        return _json_response({"ok": False, "error": "Invalid JSON body."}, status=400)
    account_id = ""
    if body:
      account_id = str(body.get("accountId") or body.get("account_id") or "").strip()
    if account_id:
      config = account_config_by_id(_PARAMS, account_id)
      if not config:
        return _json_response({"ok": False, "error": "账户不存在"}, status=404)
    else:
      config = merge_config_from_body(saved, body)
    if not config.is_configured:
      return _json_response({
        "ok": False,
        "error": config.configuration_error or "AI not configured",
        "configured": False,
        "configureError": config.configuration_error,
      })
    result = await test_connection(config)
    return _json_response({
      "ok": bool(result.get("ok")),
      "error": result.get("error"),
      "model_available": result.get("model_available"),
      "models_count": result.get("models_count"),
      "message": result.get("message"),
      "configured": True,
    })
  except Exception as e:
    cloudlog.error(f"aid: api_test_connection error: {e}")
    return _json_response({"ok": False, "error": f"Internal error: {e}"}, status=500)


async def api_skills(request: web.Request) -> web.Response:
  """List or persist enabled agent skills."""
  if request.method == "GET":
    enabled = load_enabled_skill_ids(_PARAMS)
    return _json_response({
      "ok": True,
      "skills": list_skills(),
      "enabled": sorted(enabled) if enabled else None,
    })
  try:
    body = await request.json()
  except json.JSONDecodeError:
    return _json_response({"ok": False, "error": "Invalid JSON"}, status=400)
  ids = body.get("enabled") or []
  if not isinstance(ids, list):
    return _json_response({"ok": False, "error": "enabled must be a list"}, status=400)
  save_enabled_skill_ids(_PARAMS, [str(x) for x in ids if x])
  return _json_response({"ok": True, "enabled": ids})


async def api_tools_meta(request: web.Request) -> web.Response:
  return _json_response({"ok": True, "tools": tool_meta_for_host(), "hostEnvironment": get_host_environment()})


async def api_memory(request: web.Request) -> web.Response:
  if request.method == "GET":
    return _json_response(get_memory(_PARAMS))
  try:
    body = await request.json()
  except json.JSONDecodeError:
    return _json_response({"ok": False, "error": "Invalid JSON"}, status=400)
  if body.get("delete_note_id"):
    return _json_response(delete_note(_PARAMS, str(body["delete_note_id"])))
  if body.get("note"):
    return _json_response(append_note(_PARAMS, body["note"], body.get("tags")))
  if body.get("vehicle_profile"):
    return _json_response(update_vehicle_profile(_PARAMS, body["vehicle_profile"]))
  return _json_response({"ok": False, "error": "Nothing to update"}, status=400)


async def api_scheduler(request: web.Request) -> web.Response:
  if request.method == "GET":
    return _json_response(list_tasks(_PARAMS))
  try:
    body = await request.json()
  except json.JSONDecodeError:
    return _json_response({"ok": False, "error": "Invalid JSON"}, status=400)
  if body.get("nl") or body.get("natural_language"):
    from ai.tools.scheduler import upsert_task_from_nl
    text = str(body.get("nl") or body.get("natural_language") or "")
    return _json_response(upsert_task_from_nl(_PARAMS, text))
  op = body.get("operation", "upsert")
  if op == "remove":
    return _json_response(remove_task(_PARAMS, str(body.get("task_id", ""))))
  return _json_response(upsert_task(
    _PARAMS,
    task_id=body.get("task_id"),
    name=str(body.get("name", "")),
    action=str(body.get("action", "read_last_log")),
    interval_minutes=int(body.get("interval_minutes", 60)),
    enabled=bool(body.get("enabled", True)),
    payload=body.get("payload"),
    trigger=str(body.get("trigger", "interval")),
  ))


async def api_write_confirm(request: web.Request) -> web.Response:
  try:
    body = await request.json()
  except json.JSONDecodeError:
    return _json_response({"ok": False, "error": "Invalid JSON"}, status=400)
  state = _get_state_reader().update(timeout=0)
  allowed, reason = is_action_allowed("write_param", state, admin=is_admin_mode(_PARAMS))
  if not allowed:
    return _json_response({"ok": False, "error": reason}, status=403)
  pending_id = str(body.get("pending_id", ""))
  if not pending_id:
    return _json_response({"ok": False, "error": "pending_id required"}, status=400)
  return _json_response(confirm_pending(_PARAMS, pending_id))


async def api_write_pending(request: web.Request) -> web.Response:
  return _json_response(list_pending(_PARAMS))


async def api_tune_passport(request: web.Request) -> web.Response:
  from ai.tools.tune_passport_store import list_tune_passport
  limit = int(request.query.get("limit", "30"))
  return _json_response(list_tune_passport(limit=limit))


async def api_tune_compare(request: web.Request) -> web.Response:
  try:
    body = await request.json()
  except json.JSONDecodeError:
    return _json_response({"ok": False, "error": "Invalid JSON"}, status=400)
  route_a = str(body.get("route_a") or "").strip()
  route_b = str(body.get("route_b") or "").strip()
  if not route_a or not route_b:
    return _json_response({"ok": False, "error": "route_a and route_b required"}, status=400)
  label_a = str(body.get("label_a") or "before")
  label_b = str(body.get("label_b") or "after")
  with_scores = bool(body.get("with_scores", True))
  from ai.tools.route_analysis_tools import compare_tune_ab
  compare = compare_tune_ab(route_a, route_b, label_a=label_a, label_b=label_b)
  if not compare.get("ok"):
    return _json_response(compare, status=400)
  out: dict[str, Any] = {"ok": True, "compare": compare}
  if with_scores:
    from ai.tools.route_scoring_tools import score_tune_session
    session = score_tune_session(route_a, route_b)
    out["session"] = session
  return _json_response(out)


async def api_rag(request: web.Request) -> web.Response:
  config = _read_ai_config()
  embed_cfg = load_embedding_config(_PARAMS, config)
  if request.method == "GET":
    q = request.query.get("q", "")
    if q:
      return _json_response(await search_documents(_PARAMS, q, embed_config=embed_cfg))
    return _json_response(list_documents(_PARAMS))
  try:
    body = await request.json()
  except json.JSONDecodeError:
    return _json_response({"ok": False, "error": "Invalid JSON"}, status=400)
  op = body.get("operation", "upsert")
  if op == "remove":
    return _json_response(remove_document(_PARAMS, str(body.get("doc_id", ""))))
  if op == "reindex":
    return _json_response(await reindex_all(_PARAMS, embed_cfg))
  if op == "wiki_ingest":
    from ai.fork.wiki_ingest import ingest_wikis_for_current_fork

    force = bool(body.get("force"))
    include_all = bool(body.get("all_registered"))
    max_files = int(body.get("max_files_per_repo", 45) or 45)
    return _json_response(
      ingest_wikis_for_current_fork(
        _PARAMS,
        max_files_per_repo=max_files,
        force=force,
        include_all_registered=include_all,
      )
    )
  return _json_response(await upsert_document(
    _PARAMS,
    title=str(body.get("title", "")),
    text=str(body.get("text", "")),
    tags=body.get("tags"),
    doc_id=body.get("doc_id"),
    embed_config=embed_cfg,
    reindex=body.get("reindex", True),
  ))


async def api_sessions(request: web.Request) -> web.Response:
  if request.method == "GET":
    return _json_response(get_sessions(_PARAMS))
  try:
    body = await request.json()
  except json.JSONDecodeError:
    return _json_response({"ok": False, "error": "Invalid JSON"}, status=400)
  result = save_sessions(_PARAMS, body)
  try:
    await broadcast_sessions(_PARAMS)
  except Exception as e:
    cloudlog.warning(f"aid: broadcast_sessions failed: {e}")
  return _json_response(result)


async def api_dev_assets(request: web.Request) -> web.Response:
  from ai.tools.dev_assets import list_dev_assets, resolve_dev_asset
  if request.method == "GET" and request.match_info.get("kind"):
    kind = request.match_info.get("kind", "")
    name = request.match_info.get("name", "")
    path = resolve_dev_asset(kind, name)
    if path is None:
      return web.Response(status=404, text="Not found")
    if name.lower().endswith(".opbak"):
      content_type = "application/gzip"
    else:
      import mimetypes
      content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return web.FileResponse(
      path,
      headers={
        "Content-Disposition": f'attachment; filename="{name}"',
        "Content-Type": content_type,
      },
    )
  limit = int(request.query.get("limit", "40"))
  return _json_response(list_dev_assets(limit=limit))


async def api_dev_cache(request: web.Request) -> web.Response:
  from ai.tools.dev_cache_tools import clear_dev_cache, get_cache_status

  if request.method == "GET":
    days_raw = request.query.get("days")
    mode_raw = request.query.get("mode")
    if days_raw is not None and mode_raw is not None:
      return _json_response(get_cache_status(
        days=int(days_raw),
        mode=str(mode_raw),
      ))
    return _json_response(get_cache_status())
  try:
    body = await request.json()
  except json.JSONDecodeError:
    body = {}
  groups = body.get("groups")
  if groups is not None and not isinstance(groups, list):
    groups = None
  result = clear_dev_cache(
    days=int(body.get("days", 3)),
    mode=str(body.get("mode", "within")),
    groups=groups,
  )
  status = 409 if not result.get("ok") else 200
  return _json_response(result, status=status)


async def api_model_hub_fetch(request: web.Request) -> web.Response:
  """Fetch models for a provider account and optionally cache on the account."""
  try:
    body = await request.json()
  except json.JSONDecodeError:
    body = {}
  account_id = str(body.get("accountId") or body.get("account_id") or "").strip()
  if account_id:
    config = account_config_by_id(_PARAMS, account_id)
    if not config:
      return _json_response({"ok": False, "error": "账户不存在"}, status=404)
  else:
    saved = read_ai_config()
    config = merge_config_from_body(saved, body)
  result = await list_models(config)
  models = result.get("models") or []
  if account_id and result.get("ok") and models:
    ids = [str(m.get("id") if isinstance(m, dict) else m) for m in models]
    ids = [m for m in ids if m]
    if ids:
      update_account_models(_PARAMS, account_id, ids)
  return _json_response({
    "ok": bool(result.get("ok")),
    "error": result.get("error"),
    "models": models,
    "source": result.get("source"),
    "modelHub": hub_for_api(_PARAMS),
  })


async def api_model_hub_test(request: web.Request) -> web.Response:
  try:
    body = await request.json()
  except json.JSONDecodeError:
    body = {}
  account_id = str(body.get("accountId") or body.get("account_id") or "").strip()
  if account_id:
    config = account_config_by_id(_PARAMS, account_id)
    if not config:
      return _json_response({"ok": False, "error": "账户不存在"}, status=404)
  else:
    saved = read_ai_config()
    config = merge_config_from_body(saved, body)
  if not config or not config.is_configured:
    err = config.configuration_error if config else "invalid account"
    return _json_response({"ok": False, "error": err, "configured": False})
  result = await test_connection(config)
  return _json_response({
    "ok": bool(result.get("ok")),
    "error": result.get("error"),
    "configured": True,
  })


async def api_pc_sessions(request: web.Request) -> web.Response:
  try:
    from ai.tools.pc_dev_tools import pc_list_tool_sessions
    return _json_response(pc_list_tool_sessions(limit=int(request.query.get("limit", "20"))))
  except Exception as e:
    return _json_response({"ok": False, "error": str(e)})


async def api_shell(request: web.Request) -> web.Response:
  try:
    state = _get_state_reader().update(timeout=0)
    allowed, reason = is_action_allowed("shell", state, admin=is_admin_mode(_PARAMS))
    if not allowed:
      return _json_response({"ok": False, "error": reason}, status=403)

    try:
      body = await request.json()
    except json.JSONDecodeError:
      return _json_response({"ok": False, "error": "Invalid JSON body."}, status=400)

    command_name = body.get("command", "")
    result = run_command(command_name)
    return _json_response(result)
  except Exception as e:
    cloudlog.error(f"aid: api_shell error: {e}")
    return _json_response({"ok": False, "error": f"Internal error: {e}"}, status=500)


async def api_state(request: web.Request) -> web.Response:
  try:
    reader = _get_state_reader()
    reader.update(timeout=0)
    return _json_response({"ok": True, "data": reader.latest()})
  except Exception as e:
    cloudlog.error(f"aid: api_state error: {e}")
    return _json_response({"ok": False, "error": f"Internal error: {e}"}, status=500)


async def api_usage(request: web.Request) -> web.Response:
  return _json_response({
    "ok": True,
    "usage": load_usage(_PARAMS),
    "embeddingUsage": load_embedding_usage(_PARAMS),
  })


async def api_package_version(request: web.Request) -> web.Response:
  try:
    from ai.version_info import check_update

    fetch = request.query.get("fetch", "1") not in ("0", "false", "no")
    return _json_response(check_update(fetch_remote=fetch))
  except Exception as e:
    cloudlog.error(f"aid: api_package_version error: {e}")
    return _json_response({"ok": False, "error": str(e)}, status=500)


async def api_package_update(request: web.Request) -> web.Response:
  try:
    from ai.system.host_env import is_pc_dev
    from ai.version_info import run_package_update

    state = _get_state_reader().update(timeout=0)
    if state.is_driving and not is_pc_dev():
      return _json_response({"ok": False, "error": "行驶中无法更新 op助手，请停车后重试。"}, status=403)

    try:
      body = await request.json()
    except (json.JSONDecodeError, ValueError, aiohttp.ClientPayloadError):
      body = {}
    if not body.get("confirm"):
      from ai.version_info import package_info
      pkg = package_info()
      hint = (
        "将执行 git pull 并重新集成 openpilot。请 POST confirm=true。"
        if pkg.get("is_git_install")
        else "将备份当前 ai/ 并重新克隆最新版本。请 POST confirm=true。"
      )
      return _json_response({
        "ok": True,
        "needs_confirmation": True,
        "hint": hint,
      })

    root = body.get("openpilot_root") or str(openpilot_root())
    result = run_package_update(openpilot_root=str(root))
    status = 200 if result.get("ok") else 500
    return _json_response(result, status=status)
  except Exception as e:
    cloudlog.error(f"aid: api_package_update error: {e}")
    return _json_response({"ok": False, "error": str(e)}, status=500)


async def api_fork_detect(request: web.Request) -> web.Response:
  try:
    from ai.fork.analyze_fork import analyze_fork_with_ai
    from ai.fork.detect_fork import detect_fork

    root = openpilot_root()
    do_analyze = request.query.get("analyze", "0") in ("1", "true", "yes")
    if do_analyze:
      result = await analyze_fork_with_ai(_PARAMS, root, force=request.query.get("force") in ("1", "true"))
      if result.get("ok"):
        result["detect"] = detect_fork(root)
      return _json_response(result, status=200 if result.get("ok") else 500)
    return _json_response(detect_fork(root))
  except Exception as e:
    cloudlog.error(f"aid: api_fork_detect error: {e}")
    return _json_response({"ok": False, "error": str(e)}, status=500)


async def api_fork_analyze(request: web.Request) -> web.Response:
  try:
    from ai.fork.analyze_fork import analyze_fork_with_ai

    root = openpilot_root()
    try:
      body = await request.json()
    except (json.JSONDecodeError, ValueError, aiohttp.ClientPayloadError):
      body = {}
    force = bool(body.get("force"))
    result = await analyze_fork_with_ai(_PARAMS, root, force=force)
    if result.get("ok") and result.get("analysis"):
      fid = result["analysis"].get("fork_identity") or result.get("identity", {}).get("fork_id")
      if fid:
        write_param(_PARAMS, "ai_fork_id", str(fid))
        write_param(_PARAMS, "ai_fork_profile_applied", datetime.now(timezone.utc).isoformat())
    return _json_response(result, status=200 if result.get("ok") else 500)
  except Exception as e:
    cloudlog.error(f"aid: api_fork_analyze error: {e}")
    return _json_response({"ok": False, "error": str(e)}, status=500)


async def api_fork_sync(request: web.Request) -> web.Response:
  try:
    from ai.fork.fork_sync import generate_fork_drafts, list_fork_drafts

    try:
      body = await request.json()
    except (json.JSONDecodeError, ValueError, aiohttp.ClientPayloadError):
      body = {}
    if not body.get("confirm"):
      return _json_response({
        "ok": True,
        "needs_confirmation": True,
        "hint": "AI 将先阅读 openpilot 项目并分析 fork，再生成技能/文档草稿（需人工审核）。POST confirm=true。",
        "drafts": list_fork_drafts()[:5],
      })
    result = await generate_fork_drafts(
      _PARAMS,
      force_analyze=bool(body.get("force_analyze")),
    )
    if result.get("ok") and result.get("fork_id"):
      write_param(_PARAMS, "ai_fork_id", str(result["fork_id"]))
      write_param(_PARAMS, "ai_fork_profile_applied", datetime.now(timezone.utc).isoformat())
    return _json_response(result, status=200 if result.get("ok") else 500)
  except Exception as e:
    cloudlog.error(f"aid: api_fork_sync error: {e}")
    return _json_response({"ok": False, "error": str(e)}, status=500)


async def api_fork_run_stream(request: web.Request) -> web.Response:
  """SSE stream: scan → analyze → draft with phase/reasoning/content events."""
  try:
    from ai.fork.fork_sync import run_fork_pipeline

    try:
      body = await request.json()
    except (json.JSONDecodeError, ValueError, aiohttp.ClientPayloadError):
      body = {}
    if not body.get("confirm"):
      return _json_response({
        "ok": False,
        "needs_confirmation": True,
        "error": "POST confirm=true to start fork analysis pipeline.",
      }, status=400)

    root = openpilot_root()
    force = bool(body.get("force"))
    skip_draft = bool(body.get("skip_draft"))

    async def stream_response():
      response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={"Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-cache"},
      )
      await response.prepare(request)

      async def emit(event: dict[str, Any]) -> None:
        await response.write(_sse(event))

      result: dict[str, Any] = {"ok": False}
      try:
        result = await run_fork_pipeline(
          _PARAMS,
          root,
          force=force,
          skip_draft=skip_draft,
          emit=emit,
        )
        if result.get("ok") and result.get("fork_id"):
          write_param(_PARAMS, "ai_fork_id", str(result["fork_id"]))
          write_param(_PARAMS, "ai_fork_profile_applied", datetime.now(timezone.utc).isoformat())
        elif result.get("ok") and result.get("analysis"):
          fid = (result.get("analysis") or {}).get("fork_identity") or result.get("identity", {}).get("fork_id")
          if fid:
            write_param(_PARAMS, "ai_fork_id", str(fid))
            write_param(_PARAMS, "ai_fork_profile_applied", datetime.now(timezone.utc).isoformat())
      except Exception as e:
        cloudlog.error(f"aid: api_fork_run_stream pipeline error: {e}")
        await emit({"type": "error", "error": str(e)})
        await emit({"type": "done", "ok": False, "error": str(e)})
      await response.write_eof()
      return response

    return await stream_response()
  except Exception as e:
    cloudlog.error(f"aid: api_fork_run_stream error: {e}")
    return _json_response({"ok": False, "error": str(e)}, status=500)


async def api_onboarding_profile(request: web.Request) -> web.Response:
  try:
    body = await request.json()
  except json.JSONDecodeError:
    return _json_response({"ok": False, "error": "Invalid JSON"}, status=400)
  profile = body.get("vehicle_profile")
  if not isinstance(profile, dict):
    return _json_response({"ok": False, "error": "vehicle_profile must be an object"}, status=400)
  result = update_vehicle_profile(_PARAMS, profile)
  goals = body.get("goals")
  if isinstance(goals, list) and goals:
    skill_map = {
      "tuning": "sp-tuning",
      "engage": "engage-troubleshooting",
      "adaptation": "vehicle-adaptation",
      "secoc": "secoc-toyota",
      "routes": "route-diagnostics",
    }
    enabled = set(load_enabled_skill_ids(_PARAMS))
    for g in goals:
      sid = skill_map.get(str(g).strip().lower())
      if sid:
        enabled.add(sid)
    save_enabled_skill_ids(_PARAMS, sorted(enabled))
    result["enabled_skills"] = sorted(enabled)
  return _json_response(result)


async def api_onboarding_complete(request: web.Request) -> web.Response:
  try:
    write_param_bool(_PARAMS, "ai_first_run_done", True)
    config = _read_ai_config()
    return _json_response({
      "ok": True,
      "configured": config.is_configured,
      "configureError": config.configuration_error,
    })
  except Exception as e:
    return _json_response({"ok": False, "error": str(e)}, status=500)


async def api_integrate_openpilot(request: web.Request) -> web.Response:
  try:
    from ai.system.host_env import is_pc_dev
    from ai.install.integrate_openpilot import integrate

    state = _get_state_reader().update(timeout=0)
    if state.is_driving and not is_pc_dev():
      return _json_response({"ok": False, "error": "行驶中无法集成，请停车后重试。"}, status=403)
    root = openpilot_root()
    result = integrate(root, root / "ai", force_compile=bool(request.query.get("force")))
    return _json_response(result, status=200 if result.get("ok") else 500)
  except Exception as e:
    cloudlog.error(f"aid: api_integrate_openpilot error: {e}")
    return _json_response({"ok": False, "error": str(e)}, status=500)


async def api_publish(request: web.Request) -> web.Response:
  """Publish units, settings, forge tokens, and execute publish."""
  try:
    from ai.common.publish_config import save_publish_settings
    from ai.tools.forge import forge_auth_status, set_forge_token
    from ai.tools.publish_tools import publish_changes, publish_status, set_forge_token_tool
    from ai.tools.publish_units import discover_publish_units

    if request.method == "GET":
      view = request.query.get("view", "status")
      if view == "units":
        dirty_only = request.query.get("dirty", "0") in ("1", "true")
        return _json_response(discover_publish_units(include_clean=not dirty_only))
      return _json_response(publish_status())

    try:
      body = await request.json()
    except json.JSONDecodeError:
      return _json_response({"ok": False, "error": "Invalid JSON"}, status=400)

    op = str(body.get("operation") or body.get("op") or "publish").strip().lower()

    if op in ("save_settings", "settings"):
      patch = body.get("settings") or body
      return _json_response(save_publish_settings(patch if isinstance(patch, dict) else {}))

    if op in ("set_forge_token", "forge_token"):
      return _json_response(set_forge_token_tool(
        forge=str(body.get("forge") or "github"),
        token=str(body.get("token") or ""),
        confirm=True,
      ))

    if op in ("verify_forge", "forge_verify"):
      forge = str(body.get("forge") or "github")
      token = str(body.get("token") or "").strip()
      if token:
        set_forge_token(forge, token)
      return _json_response(forge_auth_status(forge, repo_url=str(body.get("repo_url") or "")))

    if op == "publish":
      state = _get_state_reader().update(timeout=0)
      from ai.system.host_env import is_pc_dev

      def _run(*, confirm: bool) -> dict:
        if confirm:
          allowed, reason = is_action_allowed("write_param", state, admin=is_admin_mode(_PARAMS))
          if not allowed:
            return {"ok": False, "error": reason}
        return publish_changes(
          unit_id=str(body.get("unit_id") or "openpilot"),
          target_mode=str(body.get("target_mode") or ""),
          title=str(body.get("title") or ""),
          body=str(body.get("body") or ""),
          base_branch=str(body.get("base_branch") or ""),
          branch=str(body.get("branch") or ""),
          commit_message=str(body.get("commit_message") or ""),
          paths=body.get("paths"),
          draft=bool(body.get("draft")),
          remote=str(body.get("remote") or ""),
          repo_url=str(body.get("repo_url") or ""),
          severity=str(body.get("severity") or ""),
          confirm=confirm,
          params=_PARAMS,
        )

      if not body.get("confirm"):
        allowed, reason = is_action_allowed("write_param", state, admin=is_admin_mode(_PARAMS))
        if not allowed and not is_pc_dev():
          return _json_response({"ok": False, "error": reason}, status=403)
        return _json_response(_run(confirm=False))
      return _json_response(_run(confirm=True))

    return _json_response({"ok": False, "error": f"unknown operation: {op}"}, status=400)
  except Exception as e:
    cloudlog.error(f"aid: api_publish error: {e}")
    return _json_response({"ok": False, "error": str(e)}, status=500)


async def api_issues(request: web.Request) -> web.Response:
  """Issue templates, settings, and create issue."""
  try:
    from ai.common.publish_config import save_publish_settings
    from ai.tools.issue_tools import (
      create_issue,
      discover_issue_templates,
      issue_status,
      report_issue,
    )

    if request.method == "GET":
      view = request.query.get("view", "status")
      unit_id = str(request.query.get("unit_id") or "assistant")
      if view == "templates":
        return _json_response(discover_issue_templates(unit_id=unit_id))
      return _json_response(issue_status())

    try:
      body = await request.json()
    except json.JSONDecodeError:
      return _json_response({"ok": False, "error": "Invalid JSON"}, status=400)

    op = str(body.get("operation") or body.get("op") or "create").strip().lower()

    if op in ("save_settings", "settings"):
      patch = body.get("settings") or {}
      if isinstance(patch, dict) and patch.get("issue_publish"):
        return _json_response(save_publish_settings({"issue_publish": patch["issue_publish"]}))
      if isinstance(patch, dict):
        return _json_response(save_publish_settings(patch))
      return _json_response({"ok": False, "error": "invalid settings"}, status=400)

    if op == "create":
      state = _get_state_reader().update(timeout=0)
      from ai.system.host_env import is_pc_dev

      def _run(*, confirm: bool) -> dict:
        if confirm:
          allowed, reason = is_action_allowed("write_param", state, admin=is_admin_mode(_PARAMS))
          if not allowed:
            return {"ok": False, "error": reason}
        fields = body.get("fields")
        field_map = {str(k): str(v) for k, v in fields.items()} if isinstance(fields, dict) else None
        labels = body.get("labels")
        label_list = [str(x) for x in labels] if isinstance(labels, list) else None
        return create_issue(
          unit_id=str(body.get("unit_id") or "assistant"),
          target_mode=str(body.get("target_mode") or ""),
          repo_url=str(body.get("repo_url") or ""),
          template_id=str(body.get("template_id") or body.get("template") or "bug"),
          title=str(body.get("title") or ""),
          body=str(body.get("body") or ""),
          fields=field_map,
          labels=label_list,
          attach_audit=bool(body.get("attach_audit", True)),
          confirm=confirm,
          params=_PARAMS,
        )

      if not body.get("confirm"):
        allowed, reason = is_action_allowed("write_param", state, admin=is_admin_mode(_PARAMS))
        if not allowed and not is_pc_dev():
          return _json_response({"ok": False, "error": reason}, status=403)
        return _json_response(_run(confirm=False))
      return _json_response(_run(confirm=True))

    if op == "report":
      state = _get_state_reader().update(timeout=0)
      from ai.system.host_env import is_pc_dev

      def _report(*, confirm: bool) -> dict:
        if confirm:
          allowed, reason = is_action_allowed("write_param", state, admin=is_admin_mode(_PARAMS))
          if not allowed:
            return {"ok": False, "error": reason}
        return report_issue(
          kind=str(body.get("kind") or "bug"),
          unit_id=str(body.get("unit_id") or ""),
          title=str(body.get("title") or ""),
          repro_steps=str(body.get("repro_steps") or body.get("repro") or ""),
          expected=str(body.get("expected") or ""),
          actual=str(body.get("actual") or ""),
          summary=str(body.get("summary") or ""),
          proposal=str(body.get("proposal") or ""),
          severity=str(body.get("severity") or "ui"),
          attach_audit=bool(body.get("attach_audit", True)),
          confirm=confirm,
          params=_PARAMS,
        )

      if not body.get("confirm"):
        allowed, reason = is_action_allowed("write_param", state, admin=is_admin_mode(_PARAMS))
        if not allowed and not is_pc_dev():
          return _json_response({"ok": False, "error": reason}, status=403)
        return _json_response(_report(confirm=False))
      return _json_response(_report(confirm=True))

    return _json_response({"ok": False, "error": f"unknown operation: {op}"}, status=400)
  except Exception as e:
    cloudlog.error(f"aid: api_issues error: {e}")
    return _json_response({"ok": False, "error": str(e)}, status=500)


