"""Tests for the unified memory backend abstraction (T-P1.2)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import ai.tests.bootstrap_pc  # noqa: F401


class TestMemoryBackend(unittest.TestCase):
  def setUp(self):
    from ai.common.memory_backend import NotesMemoryBackend
    self._notes = NotesMemoryBackend(None)

  def _patch_daily(self):
    from ai.common import memory_backend
    real_dir = None
    store = {}
    import ai.tools.domains.core.daily_memory as dm
    real_append = dm.append_daily_memory
    def _fake_append(bullets, session_id="", title=None):
      store["_last"] = {"bullets": bullets, "session_id": session_id, "title": title}
      return {"ok": True}
    dm.append_daily_memory = _fake_append
    self.addCleanup(lambda: setattr(dm, "append_daily_memory", real_append))
    return store

  def test_default_backends_two(self):
    from ai.common.memory_backend import default_backends
    backends = default_backends(None)
    self.assertEqual(len(backends), 2)

  def test_notes_append(self):
    from ai.common.memory_backend import NotesMemoryBackend
    backend = NotesMemoryBackend(None)
    res = backend.append("test note", tags=["t"])
    self.assertTrue(res.get("ok", True))
    self.assertGreaterEqual(backend.count(), 1)

  def test_append_unified_fans_out(self):
    from ai.common.memory_backend import append_unified_memory
    store = self._patch_daily()
    result = append_unified_memory("unified observation", tags=["u"], session_id="s1", title="T")
    self.assertTrue(result["ok"])
    self.assertIn("notesmemory", result["backends"])
    self.assertIn("dailymemory", result["backends"])
    self.assertEqual(store["_last"]["title"], "T")

  def test_daily_backend_tolerates_missing_title(self):
    """Regression: DailyMemoryBackend used to pass title=None into
    append_daily_memory, which did title.strip() -> AttributeError
    ('NoneType' object has no attribute 'strip'), so the daily backend
    silently failed on every append_unified_memory() call."""
    import tempfile
    from pathlib import Path as _Path
    import ai.tools.domains.core.daily_memory as dm
    tmp = tempfile.mkdtemp()
    real_dir = dm.daily_memory_dir
    dm.daily_memory_dir = lambda: _Path(tmp)
    self.addCleanup(lambda: setattr(dm, "daily_memory_dir", real_dir))

    from ai.common.memory_backend import DailyMemoryBackend
    res = DailyMemoryBackend().append("plain bullet", session_id="s2")
    self.assertTrue(res.get("ok"), res)
    text = (res.get("path") and _Path(res["path"]).read_text(encoding="utf-8")) or ""
    self.assertIn("plain bullet", text)
    self.assertIn("会话", text)

  def test_append_unified_daily_real_backend(self):
    import tempfile
    from pathlib import Path as _Path
    import ai.tools.domains.core.daily_memory as dm
    tmp = tempfile.mkdtemp()
    real_dir = dm.daily_memory_dir
    dm.daily_memory_dir = lambda: _Path(tmp)
    self.addCleanup(lambda: setattr(dm, "daily_memory_dir", real_dir))

    from ai.common.memory_backend import append_unified_memory
    result = append_unified_memory("unified without title")
    self.assertTrue(result["results"]["dailymemory"].get("ok"), result["results"]["dailymemory"])
    self.assertTrue(result["results"]["notesmemory"].get("ok", True))

  def test_backend_kind_default(self):
    from ai.common.memory_backend import DailyMemoryBackend, NotesMemoryBackend
    self.assertEqual(NotesMemoryBackend(None).kind(), "notesmemory")
    self.assertEqual(DailyMemoryBackend().kind(), "dailymemory")


if __name__ == "__main__":
  unittest.main()