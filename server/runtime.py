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
  """Auto-calibrate the AI timezone from GPS or network (IP) — whichever is available.

  Priority:
    1. GPS fix (most accurate; needs ignition + satellite lock).
    2. Network egress IP (works without GPS / ignition — comma device calibrates
       its timezone as soon as it has internet, fulfilling "一联网就自动校准时区").

  Conservative: only writes when the detected zone differs from the current one,
  then also applies it to the OS system clock (/etc/localtime + /etc/timezone) so
  `date`, logs and routes all share the same timezone.
  """
  from ai.infra.timezone import (
    detect_timezone_from_gps,
    detect_timezone_from_ip,
    read_ai_timezone_name,
    utc_offset_hours,
  )
  from ai.common.storage import write_param

  # Small backoff: wait for services + network/GPS to warm up before first probe.
  await asyncio.sleep(30)

  cooldown_s = 600  # re-check every 10 min
  while True:
    await asyncio.sleep(cooldown_s)
    try:
      detected = None
      source = None

      # 1. Try GPS first (most accurate).
      lat, lng = await _read_gps_fix()
      if lat is not None and lng is not None:
        detected = detect_timezone_from_gps(lat, lng)
        source = f"gps(lat={lat:.3f},lng={lng:.3f})"

      # 2. Fall back to network egress IP when no GPS fix (or GPS couldn't resolve).
      if not detected:
        try:
          if await device_wifi_connected():
            # IP lookup is blocking I/O; keep it off the event loop.
            loop = asyncio.get_event_loop()
            detected = await loop.run_in_executor(None, detect_timezone_from_ip)
            source = "ip"
            if detected:
              cloudlog.info(f"aid: tz: network auto-detect -> {detected}")
        except Exception as e:
          cloudlog.debug(f"aid: tz: ip lookup failed: {e}")

      if not detected:
        cloudlog.debug("aid: tz: no GPS fix and no network zone resolved")
        continue

      current = read_ai_timezone_name(_PARAMS)
      # Only apply when the UTC offset actually changes (a real timezone move,
      # e.g. Shanghai->Tokyo +8->+9). Skip same-offset name flips (e.g. IP
      # geolocation Shanghai->Hong_Kong both +8) so the user's saved zone isn't
      # churned by cosmetic differences.
      changed = detected != current and abs(utc_offset_hours(detected) - utc_offset_hours(current)) > 0.01
      if changed:
        cloudlog.info(f"aid: tz: auto-update {current} -> {detected} ({source})")
        write_param(_PARAMS, "ai_timezone", detected)
        # Sync OS system clock so `date`/logs/routes share the same timezone.
        from ai.infra.timezone import apply_os_timezone
        apply_os_timezone(detected)
      elif detected != current:
        cloudlog.debug(f"aid: tz: same offset ({current}->{detected}), keep current")
    except Exception as e:
      cloudlog.debug(f"aid: gps tz loop: {e}")
