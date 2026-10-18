"""Background runtime loops for op助手."""

from __future__ import annotations

import asyncio
import json
import traceback
from typing import Any

from aiohttp import web

from openpilot.common.swaglog import cloudlog

from ai.server.deps import get_state_reader, params, read_ai_config
from ai.server.handlers.scheduler import scheduler_execute_action, device_wifi_connected
from ai.core.sync.hub import broadcast_status
from ai.tools.scheduler import run_due_tasks

_PARAMS = params()


async def status_watch_loop(_app: web.Application) -> None:
  last_sig: str | None = None
  while True:
    await asyncio.sleep(3)
    try:
      state = get_state_reader().update(timeout=0)
      config = read_ai_config()
      sig = json.dumps({
        "driving": state.is_driving,
        "state": state.to_dict(),
        "model": config.model,
        "provider": config.provider,
        "configured": config.is_configured,
      }, sort_keys=True, default=str)
      if sig != last_sig:
        last_sig = sig
        await broadcast_status(state, config)
    except Exception as e:
      cloudlog.debug(f"aid: status watch: {e}")


async def scheduler_loop(_app: web.Application) -> None:
  while True:
    await asyncio.sleep(60)
    try:
      state = get_state_reader().update(timeout=0)
      wifi = await device_wifi_connected()
      await run_due_tasks(
        _PARAMS,
        is_driving=lambda: state.is_driving,
        is_ignition=lambda: state.ignition,
        is_wifi=lambda: wifi,
        execute_action=scheduler_execute_action,
      )
    except Exception as e:
      cloudlog.error(f"aid: scheduler loop error: {e}")
      cloudlog.error(f"aid: scheduler loop traceback: {traceback.format_exc()}")


async def _read_gps_fix() -> tuple[float | None, float | None]:
  """Read one live GPS fix (lat, lng) or (None, None). Lazy/cheap."""
  gps_service = "gpsLocation"
  try:
    from openpilot.common.params import Params
    p = Params()
    if p.get_bool("UbloxAvailable"):
      gps_service = "gpsLocationExternal"
  except Exception:
    pass
  try:
    from openpilot.cereal import messaging
    sm = messaging.SubMaster([gps_service])
    for _ in range(6):
      try:
        sm.update(1000)
      except Exception:
        break
      if sm.updated[gps_service] and sm[gps_service].hasFix:
        return float(sm[gps_service].latitude), float(sm[gps_service].longitude)
  except Exception:
    pass
  return None, None


async def gps_auto_timezone_loop(_app: web.Application) -> None:
  """Auto-calibrate the timezone from GPS (authoritative) or network IP (opt-in).

  Priority:
    1. GPS fix — proxy-proof, the only always-on auto source.
    2. Network egress IP — OFF by default (ai_timezone_auto_network=0): a proxy/VPN
       exit node reports Asia/Singapore for a device actually in Shanghai. When
       enabled it needs NETWORK_CONFIRM_REQUIRED consecutive identical results and
       never overrides a manually pinned zone.

  Every writer funnels through infra.timezone.consider_timezone_update(), which
  also enforces the same-offset rule (Shanghai/Hong_Kong/Singapore are all +8, so
  a name-only flip is ignored instead of churning the user's setting).
  """
  from ai.infra.timezone import (
    TIMEZONE_SOURCE_GPS,
    TIMEZONE_SOURCE_NETWORK,
    consider_timezone_update,
    detect_timezone_from_gps,
    detect_timezone_from_ip,
    network_auto_enabled,
  )

  # Small backoff: wait for services + network/GPS to warm up before first probe.
  await asyncio.sleep(30)

  cooldown_s = 600  # re-check every 10 min
  while True:
    await asyncio.sleep(cooldown_s)
    try:
      detected: str | None = None
      source: str | None = None

      # 1. GPS first (most accurate, and immune to proxy exit-node geolocation).
      lat, lng = await _read_gps_fix()
      if lat is not None and lng is not None:
        detected = detect_timezone_from_gps(lat, lng)
        source = TIMEZONE_SOURCE_GPS

      # 2. Network fallback — only when explicitly enabled.
      if not detected:
        if not network_auto_enabled(_PARAMS):
          cloudlog.debug("aid: tz: no GPS fix; network auto-detect disabled")
          continue
        try:
          if await device_wifi_connected():
            loop = asyncio.get_event_loop()
            got = await loop.run_in_executor(None, detect_timezone_from_ip)
            if got:
              cloudlog.info(f"aid: tz: network auto-detect -> {got}")
              detected, source = got, TIMEZONE_SOURCE_NETWORK
        except Exception as e:
          cloudlog.debug(f"aid: tz: ip lookup failed: {e}")

      if not detected or not source:
        cloudlog.debug("aid: tz: no GPS fix and no network zone resolved")
        continue

      applied, reason = consider_timezone_update(detected, source, params=_PARAMS)
      if applied:
        cloudlog.info(f"aid: tz: applied {reason}")
      else:
        cloudlog.debug(f"aid: tz: keep current ({reason})")
    except Exception as e:
      cloudlog.debug(f"aid: gps tz loop: {e}")
