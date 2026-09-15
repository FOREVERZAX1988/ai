"""User-facing timezone helpers for route timestamps and UI (extended for GPS auto-detect)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from zoneinfo import ZoneInfo

from openpilot.common.params import Params

DEFAULT_AI_TIMEZONE = "Asia/Shanghai"

# Shown in settings dropdown (IANA id -> label key suffix).
AI_TIMEZONE_OPTIONS: list[tuple[str, str]] = [
  ("Asia/Shanghai", "Asia/Shanghai"),
  ("Asia/Tokyo", "Asia/Tokyo"),
  ("Asia/Seoul", "Asia/Seoul"),
  ("America/Los_Angeles", "America/Los_Angeles"),
  ("America/New_York", "America/New_York"),
  ("Europe/London", "Europe/London"),
  ("UTC", "UTC"),
]

# Fixed offsets when IANA tz database is unavailable (e.g. Windows without tzdata).
_TZ_FIXED_OFFSET_HOURS: dict[str, float] = {
  "Asia/Shanghai": 8,
  "Asia/Tokyo": 9,
  "Asia/Seoul": 9,
  "America/Los_Angeles": -8,
  "America/New_York": -5,
  "Europe/London": 0,
  "UTC": 0,
}

_TZFINDER = None  # lazy singleton


def _timezone_finder():
  """Lazily import/construct timezonefinder (heavy ~1.3MB data). Returns obj or None."""
  global _TZFINDER
  if _TZFINDER is None:
    try:
      import timezonefinder
      _TZFINDER = timezonefinder.TimezoneFinder()
    except Exception:
      _TZFINDER = False
  return _TZFINDER or None



def _canonical_etc_zone(zone: str) -> str:
  """Map awkward Etc/GMT+.. generated zones into the fixed-offset table used by the UI."""
  # timezonefinder returns e.g. Etc/GMT+8 for the ocean; openpilot only exposes a
  # small fixed dropdown. Fall back to the fixed-offset table by matching sign.
  key = zone.replace("Etc/GMT", "").strip()
  if not key:
    return DEFAULT_AI_TIMEZONE
  # Etc/GMT+N is UTC-N, Etc/GMT-N is UTC+N (inverted sign)
  try:
    offset_h = -1 * int(key.replace("+", "").replace("-", "-"))
    # Pure-offset search against known options (rare for land stations — keep default).
    for name, hours in _TZ_FIXED_OFFSET_HOURS.items():
      if int(hours) == offset_h and name != "UTC":
        return name
  except Exception:
    pass
  return DEFAULT_AI_TIMEZONE

def detect_timezone_from_gps(lat: float, lng: float) -> str | None:
  """Detect IANA timezone name from WGS84 coordinates (GPS). Returns None if unavailable."""
  if not lat and not lng:
    return None
  tf = _timezone_finder()
  if tf is None:
    return None
  try:
    zone = tf.timezone_at(lat=float(lat), lng=float(lng))
  except Exception:
    return None
  if not zone:
    return None
  # Normalize awkward generated names (e.g. Etc/GMT+8) to a canonical IANA zone so
  # the offset/display is correct and matches the WebUI dropdown options.
  if zone.startswith("Etc/"):
    zone = _canonical_etc_zone(zone)
  return zone


def _zone_or_fixed(name: str) -> ZoneInfo | timezone:
  try:
    return ZoneInfo(name)
  except Exception:
    if name == "UTC":
      return timezone.utc
    hours = _TZ_FIXED_OFFSET_HOURS.get(name, _TZ_FIXED_OFFSET_HOURS[DEFAULT_AI_TIMEZONE])
    return timezone(timedelta(hours=hours))


def read_ai_timezone_name(params: Params | None = None) -> str:
  from ai.common.storage import read_param
  raw = read_param(params, "ai_timezone")
  if not raw:
    return DEFAULT_AI_TIMEZONE
  name = raw.decode() if isinstance(raw, bytes) else str(raw)
  name = name.strip()
  return name or DEFAULT_AI_TIMEZONE


def get_route_timezone(params: Params | None = None) -> ZoneInfo | timezone:
  return _zone_or_fixed(read_ai_timezone_name(params))


def apply_os_timezone(tz_name: str) -> bool:
  """Apply the IANA timezone to the OS system clock (localtime files).

  The OS clock is kept in UTC (network NTP sync), but the display/route timezone
  is driven by /data/etc/localtime (+ symlinked /etc/localtime). Writing the
  correct TZinfo file here makes `date`, logs and the OS clock read back in the
  local timezone, matching what routes/Cabana display. Best-effort; never raises.

  /data is rw but /data/etc/localtime is root-owned, so a plain write may fail;
  fall back to sudo cp (the comma user is a sudoer and /data is rw ext4).
  """
  if not tz_name:
    return False
  zone_file = f"/usr/share/zoneinfo/{tz_name}"
  if not os.path.isfile(zone_file):
    zone_file = ""
  ok = False
  try:
    if zone_file:
      import shutil
      try:
        shutil.copy(zone_file, "/data/etc/localtime")
        ok = True
        # /etc/localtime -> /data/etc/localtime symlink; also fix ownership chain if we can.
      except PermissionError:
        ok = _sudo_copy(zone_file, "/data/etc/localtime")
    # Also write /etc/timezone so tools that read it see the right zone.
    try:
      with open("/etc/timezone", "w") as f:
        f.write(tz_name + "\n")
    except PermissionError:
      ok = _sudo_copy_text(tz_name + "\n", "/etc/timezone") or ok
    return ok
  except Exception:
    return False


def _sudo_copy(src: str, dst: str) -> bool:
  """Best-effort root copy via sudo (comma user is a sudoer; /data is rw)."""
  import subprocess
  try:
    r = subprocess.run(["sudo", "-n", "cp", src, dst], capture_output=True, timeout=15)
    return r.returncode == 0
  except Exception:
    return False


def _sudo_copy_text(text: str, dst: str) -> bool:
  import subprocess, sys
  try:
    r = subprocess.run(["sudo", "-n", "tee", dst], input=text.encode(), capture_output=True, timeout=15)
    return r.returncode == 0
  except Exception:
    return False


def detect_timezone_from_ip(timeout: float = 8.0) -> str | None:
  """Detect IANA timezone from the device's egress IP (network-based).

  Uses ip-api.com (no API key, returns timezone directly). This is the
  "联网自动校准时区" path — works without GPS fix / without ignition, so the
  comma device calibrates its timezone as soon as it has network access.
  Best-effort; returns None on any failure (caller keeps current zone).
  """
  import urllib.request
  url = "http://ip-api.com/json/?fields=status,lat,lon,timezone"
  try:
    with urllib.request.urlopen(url, timeout=timeout) as r:
      data = json.loads(r.read().decode("utf-8", errors="replace"))
    if data.get("status") == "success":
      tz = (data.get("timezone") or "").strip()
      if tz:
        return _canonical_etc_zone(tz) if tz.startswith("Etc/") else tz
    return None
  except Exception:
    return None


def utc_offset_hours(name: str | None) -> float:
  """Return UTC offset hours for an IANA zone (best-effort, pull from tzdata)."""
  if not name:
    name = DEFAULT_AI_TIMEZONE
  try:
    now = datetime.now(_zone_or_fixed(name))
    return now.utcoffset().total_seconds() / 3600.0 if now.utcoffset() else 0.0
  except Exception:
    return _TZ_FIXED_OFFSET_HOURS.get(name, _TZ_FIXED_OFFSET_HOURS[DEFAULT_AI_TIMEZONE])
