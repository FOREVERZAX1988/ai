"""Pure-Python CAN signal decoder (single DBC source: opendbc via cabana.dbc)."""
from __future__ import annotations

from typing import Any

# Big-endian bit order used by opendbc: index in this list == bit position in
# the 64-bit MSB-first stream; value == (byte_index * 8 + bit_in_byte).
_BE_BITS = [j + i * 8 for i in range(64) for j in range(7, -1, -1)]


def _raw_value(sig: dict[str, Any], data: bytes) -> int | None:
  """Extract the raw unsigned bit field; None if data is too short / malformed."""
  size = int(sig.get("size", 0) or 0)
  start = int(sig.get("start_bit", 0) or 0)
  if size <= 0 or size > 64:
    return None
  if sig.get("little_endian"):
    msb = start + size - 1
    if msb // 8 >= len(data):
      return None
    return int.from_bytes(data, "little") >> start & ((1 << size) - 1)
  try:
    idx = _BE_BITS.index(start)
  except ValueError:
    return None
  bits = _BE_BITS[idx: idx + size]
  if max(bits) // 8 >= len(data):
    return None
  value = 0
  for bit in bits:
    value = (value << 1) | ((data[bit // 8] >> (bit % 8)) & 1)
  return value


def decode_signal_value(sig: dict[str, Any], data: bytes) -> float:
  """Decode one signal from raw frame bytes: (raw * factor) + offset with sign fixup."""
  raw = _raw_value(sig, data)
  if raw is None:
    raise ValueError("frame data too short for signal")
  size = int(sig.get("size", 0) or 0)
  if sig.get("signed") and raw & (1 << (size - 1)):
    raw -= 1 << size
  factor = float(sig.get("factor", 1.0) or 1.0)
  offset = float(sig.get("offset", 0.0) or 0.0)
  return raw * factor + offset


def decode_frames(signals: list[dict[str, Any]], frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
  """Return frame copies with "values": {signal_name: value} attached.

  Frames whose address has no decodable signals (or undecodable data) are skipped.
  """
  by_address: dict[int, list[dict[str, Any]]] = {}
  for s in signals:
    # signal_type != 0 marks checksum / counter — not physically decodable.
    if int(s.get("signal_type", 0) or 0) != 0:
      continue
    try:
      by_address.setdefault(int(s["address"]), []).append(s)
    except (KeyError, TypeError, ValueError):
      continue
  out: list[dict[str, Any]] = []
  for f in frames:
    try:
      sigs = by_address.get(int(f.get("address", 0)))
    except (TypeError, ValueError):
      continue
    if not sigs:
      continue
    try:
      data = bytes.fromhex(str(f.get("data", "")))
    except ValueError:
      continue
    values: dict[str, float] = {}
    for s in sigs:
      try:
        values[str(s["signal"])] = decode_signal_value(s, data)
      except (ValueError, KeyError, TypeError, OverflowError):
        continue
    if not values:
      continue
    out.append({**f, "values": values})
  return out


def get_decoder(dbc_name: str) -> dict[int, list[dict[str, Any]]] | None:
  """Decodable signal table grouped by address (checksum/counter signals skipped)."""
  from ai.services.cabana.dbc import _parse_dbc_signals

  if not dbc_name:
    return None
  try:
    signals = _parse_dbc_signals(dbc_name)
  except Exception:
    return None
  if not signals:
    return None
  table: dict[int, list[dict[str, Any]]] = {}
  for s in signals:
    # signal_type != 0 marks checksum / counter — not physically decodable.
    if int(s.get("signal_type", 0) or 0) != 0:
      continue
    try:
      table.setdefault(int(s["address"]), []).append(s)
    except (TypeError, ValueError):
      continue
  return table or None
