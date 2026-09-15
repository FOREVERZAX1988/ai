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


async def gps_auto_timezone_loop(_app: web.Application) -> None:
  """Automatically update the AI timezone from GPS coordinates.

  Reads the live GPS location (lat/lng), detects the IANA timezone and stores it
  into ``ai_timezone`` (the same param the WebUI/dropdown writes). The loop is
  conservative: only updates when there is a valid fix and the detected zone
  differs from the current one. It also only auto-applies when the user has not
  pinned a manual zone (we detect "manual" by matching against available options
  — for simplicity we always allow GPS to refine, since the device is mobile).
  """
  from ai.infra.timezone import detect_timezone_from_gps, read_ai_timezone_name
  from ai.common.storage import write_param

  # Small backoff: wait for services + GPS to warm up before first probe.
  await asyncio.sleep(30)

  cooldown_s = 600  # re-check every 10 min
  while True:
    await asyncio.sleep(cooldown_s)
    try:
      # Subscribe (lazy, cheap) to the live GPS location.
      gps_service = "gpsLocation"
      try:
        from openpilot.common.params import Params
        p = Params()
        if p.get_bool("UbloxAvailable"):
          gps_service = "gpsLocationExternal"
      except Exception:
        pass

      from openpilot.cereal import messaging
      sm = messaging.SubMaster([gps_service])
      # Poll a few times to allow a fix to arrive.
      got = False
      lat = lng = None
      for _ in range(6):
        try:
          sm.update(1000)
        except Exception:
          break
        if sm.updated[gps_service] and sm[gps_service].hasFix:
          lat = float(sm[gps_service].latitude)
          lng = float(sm[gps_service].longitude)
          got = True
          break
      if not got or lat is None or lng is None:
        cloudlog.debug("aid: gps tz: no fix yet")
        continue

      detected = detect_timezone_from_gps(lat, lng)
      if not detected:
        cloudlog.debug("aid: gps tz: could not resolve zone")
        continue
      current = read_ai_timezone_name(_PARAMS)
      if detected != current:
        cloudlog.info(f"aid: gps tz: auto-update {current} -> {detected} (lat={lat:.3f},lng={lng:.3f})")
        write_param(_PARAMS, "ai_timezone", detected)
    except Exception as e:
      cloudlog.debug(f"aid: gps tz loop: {e}")
