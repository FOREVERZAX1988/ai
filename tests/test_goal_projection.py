"""Goal/Plan/Todo session event projection tests (G2/U6).

Covers: mutation → domain event append, replay fold rebuild, tombstone,
legacy no-sink compatibility, and pipeline session_ctx propagation into
thread-executed handlers.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any

import ai.tests.bootstrap_pc  # noqa: F401

from ai.core.session.folds import fold_domain_events
from ai.core.session.log import EventType, SessionEvent, SessionLog
from ai.core.tools.pipeline import ToolPipeline, session_ctx
from ai.goal.store import GoalStore
from ai.plan.store import PlanStore
from ai.todo.store import TodoStore
from ai.tools import harness_tools as ht


def _events_of_type(log: SessionLog, event_type: EventType) -> list[SessionEvent]:
  return [e for e in log.events if e.type == event_type]


class GoalProjectionTests(unittest.TestCase):
  def setUp(self) -> None:
    self.log = SessionLog("goal-proj-test")
    self.store = GoalStore(Path(tempfile.mkdtemp()) / "goals")
    self.store.set_event_sink(
      lambda snap, tomb=False: self.log.append_domain_event("goal", snap, tombstone=tomb)
    )

  def test_create_emits_goal_change_event(self) -> None:
    view = self.store.create({"objective": "ship v0.3", "max_goal_rounds": 8})
    events = _events_of_type(self.log, EventType.GOAL_CHANGE)
    self.assertEqual(len(events), 1)
    snap = events[0].data["snapshot"]
    self.assertEqual(snap["id"], view.id)
    self.assertEqual(snap["objective"], "ship v0.3")
    self.assertEqual(snap["revision"], 1)
    self.assertFalse(events[0].data["tombstone"])

  def test_replay_fold_rebuilds_state(self) -> None:
    view = self.store.create({"objective": "ship v0.3"})
    self.store.edit({"id": view.id, "revision": view.revision}, {"objective": "ship v0.4"})
    state = fold_domain_events(self.log.events)
    self.assertIsNotNone(state["goal"])
    self.assertEqual(state["goal"]["objective"], "ship v0.4")
    self.assertEqual(state["goal"]["revision"], 2)

  def test_log_derive_domain_state_matches_fold(self) -> None:
    self.store.create({"objective": "derive me"})
    self.assertEqual(self.log.derive_domain_state(), fold_domain_events(self.log.events))
    self.assertEqual(self.log.derive_domain_state()["goal"]["objective"], "derive me")

  def test_invalid_transition_emits_no_event(self) -> None:
    view = self.store.create({"objective": "x"})
    self.store.complete({"id": view.id, "revision": view.revision})
    before = len(_events_of_type(self.log, EventType.GOAL_CHANGE))
    with self.assertRaises(Exception):
      self.store.pause({"id": view.id, "revision": view.revision + 1})
    after = len(_events_of_type(self.log, EventType.GOAL_CHANGE))
    self.assertEqual(before, after)


class PlanTodoProjectionTests(unittest.TestCase):
  def setUp(self) -> None:
    self.log = SessionLog("plan-todo-proj-test")
    self.plans = PlanStore(Path(tempfile.mkdtemp()) / "plans")
    self.todos = TodoStore(Path(tempfile.mkdtemp()) / "todos")
    self.plans.set_event_sink(
      lambda snap, tomb=False: self.log.append_domain_event("plan", snap, tombstone=tomb)
    )
    self.todos.set_event_sink(
      lambda snap, tomb=False: self.log.append_domain_event("todo", snap, tombstone=tomb)
    )

  def test_plan_create_update_emit_snapshots(self) -> None:
    plan = self.plans.create(title="P1", steps=[{"id": "s1", "content": "do"}])
    plan = self.plans.update(plan.id, {"status": "active"})
    plan = self.plans.set_step_status(plan.id, "s1", "completed")
    events = _events_of_type(self.log, EventType.PLAN_CHANGE)
    self.assertEqual(len(events), 3)
    self.assertEqual(events[-1].data["snapshot"]["status"], "complete")
    state = fold_domain_events(self.log.events)
    self.assertEqual(state["plan"]["id"], plan.id)

  def test_plan_delete_emits_tombstone(self) -> None:
    plan = self.plans.create(title="to-delete")
    self.assertTrue(self.plans.delete(plan.id))
    event = _events_of_type(self.log, EventType.PLAN_CHANGE)[-1]
    self.assertTrue(event.data["tombstone"])
    self.assertEqual(fold_domain_events(self.log.events)["plan"], None)

  def test_todo_write_and_clear(self) -> None:
    self.todos.write([{"content": "a", "status": "pending"}])
    state = fold_domain_events(self.log.events)
    self.assertEqual(len(state["todo"]["todos"]), 1)
    self.todos.clear()
    event = _events_of_type(self.log, EventType.TODO_CHANGE)[-1]
    self.assertTrue(event.data["tombstone"])
    self.assertIsNone(fold_domain_events(self.log.events)["todo"])

  def test_legacy_no_sink_still_works(self) -> None:
    store = TodoStore(Path(tempfile.mkdtemp()) / "legacy")
    result = store.write([{"content": "legacy", "status": "pending"}])
    self.assertEqual(result["counts"]["pending"], 1)


class PipelineSessionCtxTests(unittest.TestCase):
  def test_ctx_propagates_to_thread_handler_and_resets(self) -> None:
    log = SessionLog("pipeline-ctx-test")
    store = TodoStore(Path(tempfile.mkdtemp()) / "ctx-todos")
    pipeline = ToolPipeline()
    pipeline.register_primitive("todo_write", lambda a: ht._h_todo_write(a))
    pipeline.register_primitive("boom", lambda a: (_ for _ in ()).throw(RuntimeError("x")))

    async def run() -> dict[str, Any]:
      return await pipeline.execute(
        call_id="t:1", name="todo_write", raw_arguments='{"todos": [{"content": "ctx", "status": "pending"}]}',
        extra={"session_ctx": log},
      )

    result = asyncio.run(run())
    self.assertTrue(result.get("ok"))
    events = [e for e in log.events if e.type == EventType.TODO_CHANGE]
    self.assertEqual(len(events), 1)
    self.assertEqual(events[0].data["snapshot"]["todos"][0]["content"], "ctx")
    # ContextVar must be reset even after a failing handler.
    async def fail_then_check() -> Any:
      await pipeline.execute(call_id="t:2", name="boom", raw_arguments="{}", extra={"session_ctx": log})
    asyncio.run(fail_then_check())
    self.assertIsNone(session_ctx.get())

  def test_no_ctx_leaves_store_unbound(self) -> None:
    async def run() -> dict[str, Any]:
      pipeline = ToolPipeline()
      pipeline.register_primitive("todo_write", lambda a: ht._h_todo_write(a))
      return await pipeline.execute(
        call_id="t:3", name="todo_write",
        raw_arguments='{"todos": [{"content": "noctx", "status": "pending"}]}',
      )
    result = asyncio.run(run())
    self.assertTrue(result.get("ok"))


if __name__ == "__main__":
  unittest.main()
