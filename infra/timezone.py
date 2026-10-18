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


def _read_tzfile_bytes(zone_file: str) -> bytes | None:
  try:
    with open(zone_file, "rb") as f:
      return f.read()
  except Exception:
    return None


def _atomic_write(dst: str, data: bytes) -> bool:
  """Atomically replace dst (regular file or symlink path) with data."""
  import tempfile
  d = os.path.dirname(dst) or "."
  try:
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tz-")
  except Exception:
    return False
  try:
    with os.fdopen(fd, "wb") as f:
      f.write(data)
    os.chmod(tmp, 0o644)
    os.replace(tmp, dst)  # replaces the symlink itself, not the zoneinfo target
    return True
  except Exception:
    try:
      os.unlink(tmp)
    except Exception:
      pass
    return False


def effective_os_zone() -> str:
  """Best-effort: which zone the OS clock actually resolves to right now."""
  link = "/etc/localtime"
  try:
    real = os.path.realpath(link)
    if real.startswith("/usr/share/zoneinfo/"):
      return real[len("/usr/share/zoneinfo/"):]
  except Exception:
    pass
  # Fall back to /etc/timezone content (may point at /data/etc/timezone).
  try:
    with open("/etc/timezone") as f:
      return f.read().strip()
  except Exception:
    return ""


def _repoint_etc_localtime(zone_file: str) -> bool:
  """Point /etc/localtime at zone_file. / is read-only on the device, so the
  symlink swap needs a temporary rw remount (restored afterwards)."""
  import subprocess
  link = "/etc/localtime"
  want = os.path.realpath(zone_file)
  try:
    if os.path.islink(link):
      if os.path.realpath(link) == want:
        return True
      cmd = f"mount -o remount,rw / && ln -sfn {zone_file} {link} && mount -o remount,ro /"
      try:
        subprocess.run(["sudo", "-n", "sh", "-c", cmd], capture_output=True, timeout=25)
      finally:
        if os.path.realpath(link) != want:
          try:
            subprocess.run(["sudo", "-n", "sh", "-c", "mount -o remount,ro /"],
                           capture_output=True, timeout=15)
          except Exception:
            pass
      return os.path.realpath(link) == want
    # Plain file (bind-mounted localtime): overwrite in place.
    data = _read_tzfile_bytes(zone_file)
    if data is None:
      return False
    return _atomic_write(link, data) or _sudo_copy(zone_file, link)
  except Exception:
    return False


def apply_os_timezone(tz_name: str) -> bool:
  """Apply an IANA timezone to the OS so `date`, logs and routes agree.

  Fixed in 1018: the old version copied the tzfile to /data/etc/localtime while
  /etc/localtime was a symlink into /usr/share/zoneinfo — i.e. it wrote a file
  nobody reads, so `date` never changed and /etc/timezone (-> /data/etc/timezone)
  could disagree with the effective zone. Now we (1) repoint /etc/localtime,
  (2) mirror /data/etc/localtime, (3) write /etc/timezone, then verify.
  Best-effort; never raises.
  """
  if not tz_name:
    return False
  zone_file = f"/usr/share/zoneinfo/{tz_name}"
  if not os.path.isfile(zone_file):
    return False
  ok = _repoint_etc_localtime(zone_file)
  # Mirror to /data/etc/localtime for anything that reads the /data copy.
  try:
    data = _read_tzfile_bytes(zone_file)
    dst = "/data/etc/localtime"
    if data is not None and os.path.isdir("/data/etc"):
      if _read_tzfile_bytes(dst) != data:
        if not _atomic_write(dst, data):
          _sudo_copy(zone_file, dst)
  except Exception:
    pass
  # /etc/timezone is a symlink to /data/etc/timezone on the device.
  text = tz_name + "\n"
  try:
    try:
      with open("/etc/timezone") as f:
        same = f.read() == text
    except Exception:
      same = False
    if not same:
      if not _atomic_write("/etc/timezone", text.encode()):
        _sudo_copy_text(text, "/etc/timezone")
  except Exception:
    pass
  eff = effective_os_zone()
  if eff and eff != tz_name:
    # Effective zone still disagrees (read-only root refused the swap).
    return ok and False
  return ok or eff == tz_name


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


# --- auto-detect policy (1018) -------------------------------------------------
# Proxy/VPN egress makes ip-api report a foreign zone (a Shanghai device behind a
# Singapore exit node resolves to Asia/Singapore), so network auto-detect is OFF
# unless the user explicitly enables it. GPS stays the authoritative source.
TIMEZONE_SOURCE_MANUAL = "manual"
TIMEZONE_SOURCE_GPS = "gps"
TIMEZONE_SOURCE_NETWORK = "network"
NETWORK_AUTO_DEFAULT = False
NETWORK_CONFIRM_REQUIRED = 3


def read_timezone_source(params: Params | None = None) -> str:
  from ai.common.storage import read_param
  raw = read_param(params, "ai_timezone_source")
  if not raw:
    return ""
  return (raw.decode() if isinstance(raw, bytes) else str(raw)).strip()


def write_timezone_source(source: str, params: Params | None = None) -> None:
  from ai.common.storage import write_param
  try:
    write_param(params, "ai_timezone_source", source)
  except Exception:
    pass


def network_auto_enabled(params: Params | None = None) -> bool:
  from ai.common.storage import read_param_bool
  return read_param_bool(params, "ai_timezone_auto_network", NETWORK_AUTO_DEFAULT)


def _zone_known(name: str | None) -> bool:
  if not name:
    return False
  return os.path.isfile(f"/usr/share/zoneinfo/{name}") or name in _TZ_FIXED_OFFSET_HOURS


def _bump_network_confirmations(params: Params | None, candidate: str) -> int:
  """Count consecutive identical network detections (persisted, so a reboot or a
  one-shot wifi-join trigger keeps accumulating instead of restarting at 1)."""
  from ai.common.storage import read_param, write_param
  prev = read_param(params, "ai_timezone_net_candidate") or ""
  if isinstance(prev, bytes):
    prev = prev.decode(errors="replace")
  prev = str(prev).strip()
  try:
    hits = int(str(read_param(params, "ai_timezone_net_hits") or "0").strip() or "0")
  except Exception:
    hits = 0
  hits = hits + 1 if prev == candidate else 1
  write_param(params, "ai_timezone_net_candidate", candidate)
  write_param(params, "ai_timezone_net_hits", str(hits))
  return hits


def _reset_network_confirmations(params: Params | None) -> None:
  from ai.common.storage import write_param
  write_param(params, "ai_timezone_net_candidate", "")
  write_param(params, "ai_timezone_net_hits", "0")


def consider_timezone_update(detected: str | None, source: str, *, params: Params | None = None,
                             confirmations: int = 1) -> tuple[bool, str]:
  """Single gate for every auto timezone writer. Returns (applied, reason)."""
  if not detected:
    return False, "no-detection"
  if not _zone_known(detected):
    return False, f"unknown-zone({detected})"
  params = params if params is not None else Params()
  current = read_ai_timezone_name(params)
  if detected == current:
    return False, "unchanged"
  if abs(utc_offset_hours(detected) - utc_offset_hours(current)) <= 0.01:
    # Same-offset name flip (Shanghai/Hong_Kong/Singapore/Taipei are all +8).
    return False, f"same-offset({current}->{detected})"
  if source == TIMEZONE_SOURCE_NETWORK:
    if not network_auto_enabled(params):
      return False, "network-auto-disabled"
    if read_timezone_source(params) == TIMEZONE_SOURCE_MANUAL:
      return False, "manual-pinned"
    hits = max(int(confirmations or 1), _bump_network_confirmations(params, detected))
    if hits < NETWORK_CONFIRM_REQUIRED:
      return False, f"need-confirm({hits}/{NETWORK_CONFIRM_REQUIRED})"
    _reset_network_confirmations(params)
  from ai.common.storage import write_param
  write_param(params, "ai_timezone", detected)
  write_timezone_source(source, params)
  applied = apply_os_timezone(detected)
  return True, f"{current}->{detected} applied_os={applied}"
