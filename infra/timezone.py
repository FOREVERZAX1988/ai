"""User-facing timezone helpers for route timestamps and UI (extended for GPS auto-detect)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
