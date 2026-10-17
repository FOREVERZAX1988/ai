import asyncio
import time
import unittest

from ai.core.chat import jobs


class _Break(Exception):
  pass


def _make_job(job_id: str, idle_sec: int, inflight: int = 0, run_sec: int | None = None,
              tool_calls: int = 0) -> dict:
  idle_base = int(time.time()) - idle_sec
  created = int(time.time()) - (idle_sec if run_sec is None else run_sec)
  job = {
    "id": job_id,
    "sessionId": "s_test",
    "status": "running",
    "events": [],
    "eventSeq": 0,
    "assistant": {},
    "createdAt": created,
    "updatedAt": idle_base,
    "lastEventAt": idle_base,
    "inflightTools": inflight,
    "toolCallsCompleted": tool_calls,
  }
  jobs._jobs[job_id] = job
  return job


async def _one_watchdog_iteration() -> None:
  """Run exactly one watchdog scan, then break out of its infinite loop."""
  real_sleep = jobs.asyncio.sleep
  calls = {"n": 0}

  async def fake_sleep(_delay):
    calls["n"] += 1
    if calls["n"] >= 2:
      raise _Break
    return None

  jobs.asyncio.sleep = fake_sleep
  try:
    await jobs.stuck_job_watchdog_loop()
  except _Break:
    pass
  finally:
    jobs.asyncio.sleep = real_sleep


class StuckWatchdogTest(unittest.TestCase):
  def setUp(self) -> None:
    jobs._jobs.clear()
    jobs._cancel_flags.clear()
    jobs._tasks.clear()

  def tearDown(self) -> None:
    jobs._jobs.clear()
    jobs._cancel_flags.clear()
    jobs._tasks.clear()

  def test_scan_ignores_jobs_with_tools_in_flight(self):
    _make_job("job_idle", idle_sec=400)
    _make_job("job_tool", idle_sec=400, inflight=1)
    stuck_ids = [c["jobId"] for c in jobs._scan_stuck_jobs()]
    self.assertIn("job_idle", stuck_ids)
    self.assertNotIn("job_tool", stuck_ids)

  def test_watchdog_only_warns_while_idle_is_short_of_the_cancel_threshold(self):
    # 2026-10-17: 400 s of silence is normal for this stack (one long tool body, or a model
    # that thinks before its first delta). It used to be a cancel; now it is a warning.
    _make_job("job_warn", idle_sec=400)
    asyncio.run(_one_watchdog_iteration())
    self.assertEqual(jobs._jobs["job_warn"]["status"], "running")

  def test_watchdog_cancels_a_truly_stuck_job(self):
    _make_job("job_stuck", idle_sec=jobs._STUCK_CANCEL_SEC + 60)
    asyncio.run(_one_watchdog_iteration())
    self.assertEqual(jobs._jobs["job_stuck"]["status"], "cancelled")

  def test_a_productive_long_turn_is_not_cut_at_the_old_ten_minute_mark(self):
    # Regression for "答到一半断联": a 20-minute turn that completed nine tool calls is real
    # work, not a loop, so the flat 600 s wall-clock kill must not fire.
    _make_job("job_long", idle_sec=5, run_sec=1200, tool_calls=9)
    asyncio.run(_one_watchdog_iteration())
    self.assertEqual(jobs._jobs["job_long"]["status"], "running")
    self.assertGreater(jobs.run_budget_sec(jobs._jobs["job_long"]), 1200)

  def test_run_budget_grows_per_tool_and_is_capped(self):
    base = jobs.run_budget_sec({"toolCallsCompleted": 0})
    self.assertEqual(base, jobs._RUN_MAX_SEC)
    self.assertEqual(jobs.run_budget_sec({"toolCallsCompleted": 3}),
                     jobs._RUN_MAX_SEC + 3 * jobs._RUN_EXTEND_PER_TOOL_SEC)
    self.assertEqual(jobs.run_budget_sec({"toolCallsCompleted": 10_000}), jobs._RUN_MAX_CAP_SEC)
    self.assertIsNone(jobs._jobs.get("nope"))
    self.assertEqual(jobs.run_budget_sec(None), jobs._RUN_MAX_SEC)

  def test_a_turn_that_never_produces_anything_past_budget_is_cancelled(self):
    # No tool calls, well past the base budget, and events are still flowing: that is the
    # repetition loop the wall-clock guard exists for, so it must still fire.
    _make_job("job_loop", idle_sec=5, run_sec=jobs._RUN_MAX_SEC + 60, tool_calls=0)
    asyncio.run(_one_watchdog_iteration())
    self.assertEqual(jobs._jobs["job_loop"]["status"], "cancelled")

  def test_lifecycle_phases_sent_by_the_watchdog_pass_the_ws_schema(self):
    from ai.core.sync.protocol import validate_ws_message
    for phase in ("stuck", "stuck_cancelled", "run_timeout_warn", "run_timeout"):
      ok, err = validate_ws_message({
        "type": "lifecycle", "phase": phase, "runId": "job_x", "jobId": "job_x",
        "sessionId": "s_test", "idleSec": 400, "runSec": 700,
      })
      self.assertTrue(ok, f"{phase}: {err}")

  def test_watchdog_spares_a_job_whose_tool_is_still_running(self):
    # Regression: a multi-minute `run_shell_command` emits no chat events while it
    # executes, so idle keeps growing. Cancelling that job cut the answer in half.
    _make_job("job_tool", idle_sec=400, inflight=1)
    asyncio.run(_one_watchdog_iteration())
    self.assertEqual(jobs._jobs["job_tool"]["status"], "running")

  def test_mark_tool_inflight_refreshes_the_idle_clock(self):
    job = _make_job("job_mark", idle_sec=400)
    jobs.mark_tool_inflight("job_mark", 1)
    self.assertEqual(job["inflightTools"], 1)
    self.assertLessEqual(abs(int(time.time()) - job["lastEventAt"]), 1)
    jobs.mark_tool_inflight("job_mark", -1)
    self.assertEqual(job["inflightTools"], 0)
    jobs.mark_tool_inflight("job_mark", -1)
    self.assertEqual(job["inflightTools"], 0)


if __name__ == "__main__":
  unittest.main()
