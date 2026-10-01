"""chat_status frames must satisfy the ws schema (regression: dropped job updates)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))


class TestChatStatusFrame(unittest.TestCase):
  def test_frames_validate_for_every_job_shape(self):
    try:
      from ai.core.sync.protocol import validate_ws_message
    except Exception as exc:  # pragma: no cover - optional deps
      self.skipTest(f"protocol unavailable: {exc}")
    from ai.core.sync.hub import chat_status_frame

    jobs = [
      {"status": "running"},
      {"status": "done", "assistant": {"text": "hi"}, "eventSeq": 12},
      {"status": "error", "error": None, "resolvedModel": None},
      {"status": "error", "error": "boom"},
      {"status": "cancelled", "error": {"message": "cancelled"}, "resolvedModel": 7},
    ]
    for job in jobs:
      frame = chat_status_frame("job-1", "sess-1", job)
      ok, err = validate_ws_message(frame)
      self.assertTrue(ok, f"{job} -> {err}")

  def test_optional_fields_are_omitted_when_empty(self):
    from ai.core.sync.hub import chat_status_frame

    frame = chat_status_frame("j", "s", {"status": "done", "error": None, "resolvedModel": None, "assistant": None})
    self.assertNotIn("error", frame)
    self.assertNotIn("resolvedModel", frame)
    self.assertNotIn("assistant", frame)
    self.assertEqual(frame["status"], "done")


if __name__ == "__main__":
  unittest.main()
