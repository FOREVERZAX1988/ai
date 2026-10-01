"""Regression: search_tools / load_tool must work on the AgentLoop path.

Bug: chat runs with ai_use_agent_loop=True by default, and AgentLoop executes
every tool through ToolPipeline.  The special-tool branch that handled
search_tools / load_tool lived only in Agent._run_tool_calls, so the meta tools
were never registered as pipeline primitives -> the model got
"Tool 'load_tool' not implemented" (UNKNOWN_TOOL) and, with deferred loading on,
every non-core tool stayed permanently unreachable.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

import ai.tests.bootstrap_pc  # noqa: F401 — mocks openpilot on PC


def _reader() -> Any:
  return lambda: SimpleNamespace(update=lambda timeout=0: SimpleNamespace(is_driving=False), brand="")


def _make_agent(session_id: str):
  from ai.core.agent.agent import Agent
  from ai.core.llm.client import AIConfig
  from openpilot.common.params import Params

  async def _emit(_event: dict[str, Any]) -> None:
    pass

  return Agent(
    session_id=session_id,
    agent_id="op",
    params=Params(),
    config=AIConfig(provider="offline", model="offline-mock", api_key=""),
    body={},
    emit=_emit,
    get_state_reader=_reader(),
    get_tool_handlers=lambda: {},
    tools=None,
  )


class MetaToolPipelineTests(unittest.TestCase):
  def test_meta_tools_resolve_on_pipeline(self) -> None:
    from ai.tools.deferred_loading import apply_deferred_filter, session_key

    agent = _make_agent("meta-tools-test")
    # The bug: these were unknown to the pipeline the AgentLoop actually uses.
    self.assertIsNotNone(agent.pipeline.get("search_tools"))
    self.assertIsNotNone(agent.pipeline.get("load_tool"))

    catalog = [
      {"type": "function", "function": {"name": "write_file", "description": "write a file"}},
      {"type": "function", "function": {"name": "read_file", "description": "read a file"}},
    ]
    key = session_key("meta-tools-test", "")
    apply_deferred_filter(catalog, key)

    search = asyncio.run(agent.pipeline.execute(
      call_id="c1", name="search_tools", raw_arguments='{"query": "write file"}'))
    self.assertTrue(search.get("ok"), search)
    self.assertTrue(any(h["name"] == "write_file" for h in search.get("tools", [])))

    load = asyncio.run(agent.pipeline.execute(
      call_id="c2", name="load_tool", raw_arguments='{"tools": ["write_file"]}'))
    self.assertTrue(load.get("ok"), load)
    self.assertIn("write_file", load.get("loaded", []))

    # Loading must unlock the tool for the next round.
    passed = apply_deferred_filter(catalog, key) or []
    self.assertIn("write_file", {t["function"]["name"] for t in passed})


@dataclass
class _Chunk:
  error: str | None = None
  done: bool = False
  content: str = ""
  reasoning_content: str = ""
  tool_calls: list[dict[str, Any]] = field(default_factory=list)


class LoopToolsRefreshTests(unittest.TestCase):
  def test_request_tools_refresh_each_turn(self) -> None:
    """A deferred-loaded tool must reach the model on the following turn."""
    from ai.core.agent.loop import AgentLoop
    from ai.core.tools.pipeline import ToolPipeline

    requests: list[dict[str, Any]] = []

    def _stream_fn(request: dict[str, Any], _params: Any) -> Any:
      requests.append(request)

      async def _gen() -> Any:
        yield _Chunk(content="done")
        yield _Chunk(done=True)
      return _gen()

    provider: list[dict[str, Any]] = []

    def _tools_provider() -> list[dict[str, Any]] | None:
      return list(provider) or None

    async def _emit(_event: dict[str, Any]) -> None:
      pass

    loop = AgentLoop(
      session_id="sess-refresh",
      agent_id="agent-refresh",
      params=None,
      emit=_emit,
      stream_fn=_stream_fn,
      tool_pipeline=ToolPipeline({"echo": lambda _args: {"ok": True}}),
      tools_provider=_tools_provider,
    )
    provider.append({"type": "function", "function": {"name": "echo", "description": "", "parameters": {"type": "object", "properties": {}}}})
    loop.configure_request(provider="p", model="m", system="s", tools=[])

    async def _drive() -> Any:
      await loop.add_user_message("hi", wakeup=False)
      loop.state.wake_driver()
      return await loop._run()

    result = asyncio.run(_drive())
    self.assertTrue(result.get("ok"), result)
    self.assertEqual(
      [t["function"]["name"] for t in (requests[0].get("tools") or [])],
      ["echo"],
    )


if __name__ == "__main__":
  unittest.main()
