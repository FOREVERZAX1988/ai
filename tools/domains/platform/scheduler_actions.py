"""Scheduler action implementations (sync); called from aid._scheduler_execute_action."""

from __future__ import annotations

import asyncio
import functools
from typing import Any, Callable


def _to_thread(fn, *args, **kwargs):
  """Run a synchronous callable off the event loop."""
  loop = asyncio.get_running_loop()
  if kwargs:
    return loop.run_in_executor(None, functools.partial(fn, *args, **kwargs))
  return loop.run_in_executor(None, fn, *args)


async def execute_scheduler_action(
  action: str,
  payload: dict[str, Any],
  *,
  params,
  get_state_reader: Callable,
  notify_push: Callable,
  append_note: Callable,
) -> str:
  if action == "check_runner_health_offroad":
    from ai.tools.domains.devops.github_actions_tools import check_github_runner_health
    res = await _to_thread(check_github_runner_health, notify=bool(payload.get("notify", True)))
    if not res.get("healthy"):
      issues = ", ".join(res.get("issues") or [])
      return f"issues: {issues}"
    return "runner/ci healthy"

  if action == "check_device_health_offroad":
    from ai.tools.domains.platform.device_health_tools import device_health
    h = await _to_thread(device_health)
    issues = []
    disk = h.get("disk") or {}
    if disk.get("free_gb") is not None and float(disk["free_gb"]) < 3:
      issues.append(f"disk={disk['free_gb']}GB")
    if h.get("max_temp_c") is not None and float(h["max_temp_c"]) > 90:
      issues.append(f"temp={h['max_temp_c']}C")
    if issues:
      await notify_push("设备健康", "; ".join(issues), level="warn")
      return "warn: " + "; ".join(issues)
    return "device health ok"

  if action == "check_github_ci_failed":
    from ai.tools.domains.devops.github_actions_tools import check_github_runner_health
    res = await _to_thread(check_github_runner_health, notify=False)
    fails = res.get("recent_failures") or []
    if fails:
      rid = fails[0].get("id")
      await notify_push("CI 编译失败", f"run {rid} failed", level="error")
      return f"ci failure run={rid}"
    return "no recent ci failure"

  if action == "ota_preflight_offroad":
    from ai.tools.domains.devops.branch_tools import ota_preflight_checklist
    res = await _to_thread(ota_preflight_checklist, params)
    if not res.get("ready"):
      blockers = ", ".join(res.get("blockers") or [])
      await notify_push("OTA 预检未通过", blockers, level="warn")
      return f"blockers: {blockers}"
    return "ota preflight ok"

  if action == "sync_timezone_wifi":
    """On-network-connect timezone calibration (一联网就自动校准时区).

    Runs when the device joins WiFi (on_wifi trigger). Detects the timezone from
    the network egress IP (works without GPS fix / ignition) and, if the UTC
    offset differs from the saved zone, updates ai_timezone + OS system clock.
    """
    from ai.infra.timezone import detect_timezone_from_ip, read_ai_timezone_name, apply_os_timezone, utc_offset_hours
    from ai.common.storage import write_param
    try:
      detected = await _to_thread(detect_timezone_from_ip)
      if not detected:
        return "no ip zone"
      current = read_ai_timezone_name(params)
      if detected != current and abs(utc_offset_hours(detected) - utc_offset_hours(current)) > 0.01:
        write_param(params, "ai_timezone", detected)
        applied = await _to_thread(apply_os_timezone, detected)
        return f"tz {current}->{detected} applied={applied}"
      return "tz unchanged"
    except Exception as e:
      return f"tz error: {e}"

  return ""
