import asyncio
import time
import unittest

from ai.core.chat import jobs


class _Break(Exception):
  pass


def _make_job(job_id: str, idle_sec: int, inflight: int = 0) -> dict:
  created = int(time.time()) - idle_sec
  job = {
    "id": job_id,
    "sessionId": "s_test",
    "status": "running",
    "events": [],
    "eventSeq": 0,
    "assistant": {},
    "createdAt": created,
    "updatedAt": created,
    "lastEventAt": created,
    "inflightTools": inflight,
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

  def test_watchdog_cancels_a_truly_stuck_job(self):
    _make_job("job_stuck", idle_sec=400)
    asyncio.run(_one_watchdog_iteration())
    self.assertEqual(jobs._jobs["job_stuck"]["status"], "cancelled")

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
