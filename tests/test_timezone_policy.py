"""Timezone auto-detect policy: proxy-safe guards (no openpilot compile required)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))


class TestTimezonePolicy(unittest.TestCase):
  def setUp(self):
    from ai.common.config_store import reset_config_store_for_tests
    self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    self.store = reset_config_store_for_tests(Path(self._tmp.name) / "config.json")
    self.store.put("ai_timezone", "Asia/Shanghai")

    import ai.infra.timezone as tzmod
    self.tzmod = tzmod
    self._real_apply = tzmod.apply_os_timezone
    self.applied_os: list[str] = []

    def _fake_apply(name: str) -> bool:
      self.applied_os.append(name)
      return True

    tzmod.apply_os_timezone = _fake_apply

  def tearDown(self):
    self.tzmod.apply_os_timezone = self._real_apply
    from ai.common.config_store import reset_config_store_for_tests
    # Cancel any pending debounced save before the temp dir disappears.
    try:
      self.store.reload()
    except Exception:
      pass
    reset_config_store_for_tests(None)
    self._tmp.cleanup()

  # -- guards ---------------------------------------------------------------
  def test_same_offset_flip_is_ignored(self):
    # A Singapore/Hong_Kong exit node is still +8: never churn the user's zone.
    applied, reason = self.tzmod.consider_timezone_update(
      "Asia/Singapore", self.tzmod.TIMEZONE_SOURCE_NETWORK)
    self.assertFalse(applied)
    self.assertTrue(reason.startswith("same-offset("), reason)
    self.assertEqual(self.store.get("ai_timezone"), "Asia/Shanghai")
    self.assertEqual(self.applied_os, [])

  def test_network_detection_off_by_default(self):
    applied, reason = self.tzmod.consider_timezone_update(
      "Asia/Tokyo", self.tzmod.TIMEZONE_SOURCE_NETWORK, confirmations=99)
    self.assertFalse(applied)
    self.assertEqual(reason, "network-auto-disabled")
    self.assertFalse(self.tzmod.network_auto_enabled())

  def test_manual_pin_blocks_network(self):
    self.store.put("ai_timezone_auto_network", "1")
    self.store.put("ai_timezone_source", self.tzmod.TIMEZONE_SOURCE_MANUAL)
    applied, reason = self.tzmod.consider_timezone_update(
      "Asia/Tokyo", self.tzmod.TIMEZONE_SOURCE_NETWORK, confirmations=99)
    self.assertFalse(applied)
    self.assertEqual(reason, "manual-pinned")

  def test_network_needs_three_consecutive_confirmations(self):
    self.store.put("ai_timezone_auto_network", "1")
    src = self.tzmod.TIMEZONE_SOURCE_NETWORK
    first = self.tzmod.consider_timezone_update("Asia/Tokyo", src)
    second = self.tzmod.consider_timezone_update("Asia/Tokyo", src)
    self.assertEqual(first, (False, "need-confirm(1/3)"))
    self.assertEqual(second, (False, "need-confirm(2/3)"))
    third = self.tzmod.consider_timezone_update("Asia/Tokyo", src)
    self.assertTrue(third[0], third)
    self.assertEqual(self.store.get("ai_timezone"), "Asia/Tokyo")
    self.assertEqual(self.store.get("ai_timezone_source"), src)
    self.assertEqual(self.applied_os, ["Asia/Tokyo"])
    # Counter reset -> next single detection must start over.
    applied, reason = self.tzmod.consider_timezone_update("America/New_York", src)
    self.assertFalse(applied)
    self.assertEqual(reason, "need-confirm(1/3)")

  def test_candidate_change_restarts_count(self):
    self.store.put("ai_timezone_auto_network", "1")
    src = self.tzmod.TIMEZONE_SOURCE_NETWORK
    self.tzmod.consider_timezone_update("Asia/Tokyo", src)
    self.tzmod.consider_timezone_update("Asia/Tokyo", src)
    # Proxy exit node flapped to another zone -> evidence restarts at 1.
    applied, reason = self.tzmod.consider_timezone_update("America/New_York", src)
    self.assertFalse(applied)
    self.assertEqual(reason, "need-confirm(1/3)")

  # -- gps ---------------------------------------------------------------
  def test_gps_applies_immediately_on_real_move(self):
    applied, reason = self.tzmod.consider_timezone_update(
      "Asia/Tokyo", self.tzmod.TIMEZONE_SOURCE_GPS)
    self.assertTrue(applied, reason)
    self.assertEqual(self.store.get("ai_timezone"), "Asia/Tokyo")
    self.assertEqual(self.store.get("ai_timezone_source"), self.tzmod.TIMEZONE_SOURCE_GPS)

  def test_gps_ignores_network_switch_flag(self):
    self.assertFalse(self.tzmod.network_auto_enabled())
    applied, _ = self.tzmod.consider_timezone_update(
      "America/New_York", self.tzmod.TIMEZONE_SOURCE_GPS)
    self.assertTrue(applied)

  # -- input validation ---------------------------------------------------
  def test_unknown_or_empty_zone_rejected(self):
    self.assertEqual(self.tzmod.consider_timezone_update(None, self.tzmod.TIMEZONE_SOURCE_GPS),
                     (False, "no-detection"))
    applied, reason = self.tzmod.consider_timezone_update(
      "Mars/Olympus_Mons", self.tzmod.TIMEZONE_SOURCE_GPS)
    self.assertFalse(applied)
    self.assertTrue(reason.startswith("unknown-zone("), reason)

  def test_unchanged_is_noop(self):
    applied, reason = self.tzmod.consider_timezone_update(
      "Asia/Shanghai", self.tzmod.TIMEZONE_SOURCE_GPS)
    self.assertEqual((applied, reason), (False, "unchanged"))

  # -- os timezone writer ------------------------------------------------
  def test_effective_os_zone_reads_realpath(self):
    eff = self.tzmod.effective_os_zone()
    self.assertIsInstance(eff, str)


if __name__ == "__main__":
  unittest.main()
