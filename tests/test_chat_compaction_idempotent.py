"""Regression: chat compaction must not re-summarize on every request.

Root cause guarded here: once the user-turn threshold is crossed, clients keep
resending the full transcript, so `_needs_compaction` stayed True every turn
and `maybe_compact_messages` re-summarized (and re-appended a note) each time.
That flooded memory with near-duplicate "[会话摘要]" notes, which are injected
into the per-turn prompt window -> the model re-reads/re-answers settled
questions and loses track of what it just said.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import ai.tests.bootstrap_pc  # noqa: F401  (PC openpilot mocks)

from ai.common import config_store as cs
from ai.core.chat import compaction as C


def _msgs(turns: int) -> list[dict]:
  out: list[dict] = []
  for i in range(turns):
    out.append({"role": "user", "content": f"q{i}"})
    out.append({"role": "assistant", "content": f"a{i}"})
  return out


class IdempotentCompactionTest(unittest.IsolatedAsyncioTestCase):
  def setUp(self) -> None:
    self.tmp = TemporaryDirectory()
    cs.reset_config_store_for_tests(Path(self.tmp.name) / "config.json")
    store = cs.get_config_store()
    store.put("ai_compaction_enabled", 1)
    store.put("ai_compact_after_turns", 4)
    store.put("ai_keep_recent_turns", 2)
    store.put("ai_compaction_token_trigger", 0)
    self.calls: list[list[dict]] = []

    import ai.core.llm.model_router as mr
    self._orig_cf = mr.chat_completion_collect_with_failover

    async def _fake(config, params, messages, **kw):
      self.calls.append(messages)
      return ("summary: bullets", None, None, None)

    mr.chat_completion_collect_with_failover = _fake

    import ai.tools.daily_memory as dm
    self._orig_dm = dm.append_daily_memory
    dm.append_daily_memory = lambda **kw: {"ok": True}

    self.config = SimpleNamespace(model="deepseek-v4-flash")

  def tearDown(self) -> None:
    import ai.core.llm.model_router as mr
    mr.chat_completion_collect_with_failover = self._orig_cf
    import ai.tools.daily_memory as dm
    dm.append_daily_memory = self._orig_dm
    self.tmp.cleanup()

  async def _compact(self, msgs, *, session_id="s1", force=False):
    return await C.maybe_compact_messages(msgs, None, self.config, session_id=session_id, force=force)

  async def test_compacts_once_then_waits_for_fresh_turns(self) -> None:
    m5 = _msgs(5)
    await self._compact(m5)
    self.assertEqual(len(self.calls), 1, "first crossing should compact")
    # same transcript resent next turn -> must NOT re-summarize
    await self._compact(m5)
    self.assertEqual(len(self.calls), 1, "no new turns -> no re-compaction")
    # one new turn (< keep_recent_turns=2) still not enough
    await self._compact(_msgs(6))
    self.assertEqual(len(self.calls), 1, "below keep_recent window -> skip")
    # a fresh window of 2 new turns -> compact again
    await self._compact(_msgs(7))
    self.assertEqual(len(self.calls), 2, "fresh window -> compact")

  async def test_hwm_persisted_and_shared_across_process_like_reads(self) -> None:
    await self._compact(_msgs(5), session_id="abc")
    raw = cs.get_config_store().get("ai_compaction_hwm", "")
    self.assertIn("abc", raw)

  async def test_force_bypasses_high_water_mark(self) -> None:
    m5 = _msgs(5)
    await self._compact(m5)
    self.assertEqual(len(self.calls), 1)
    await self._compact(m5, force=True)
    self.assertEqual(len(self.calls), 2, "explicit /compact must always run")


class MemoryWindowDedupTest(unittest.TestCase):
  def setUp(self) -> None:
    self.tmp = TemporaryDirectory()
    cs.reset_config_store_for_tests(Path(self.tmp.name) / "config.json")
    from ai.tools.memory_store import append_note
    params = None
    append_note(params, "用户偏好：跟车距离设为远", tags=["pref"])
    for i in range(4):
      append_note(params, f"[会话摘要]\n## 结论\n- 行驶预览属预期行为(第{i}次)", tags=["compaction"])

  def tearDown(self) -> None:
    self.tmp.cleanup()

  def test_injected_window_keeps_one_compaction_and_real_facts(self) -> None:
    from ai.tools.memory_store import format_memory_prompt
    prompt = format_memory_prompt(None, max_notes=5)
    section = prompt.split("## Recent memory notes", 1)[1] if "## Recent memory notes" in prompt else ""
    self.assertEqual(section.count("[会话摘要]"), 1, "only the latest compaction summary is injected")
    self.assertIn("跟车距离", section, "stable preference must survive the compaction spam")


if __name__ == "__main__":
  unittest.main()
