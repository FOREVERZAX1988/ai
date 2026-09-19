"""Stable WorkflowEngine tool bridge (T-P0.5, T-P1.7).

The naive bridge rebuilt ``make_handlers()`` on every TOOL step, which is
expensive and drops caller state (params / reader / audit). This adapter
caches a single handler map for the life of a run, wraps sync/async handlers
uniformly, honors cooperative cancellation through ``RunContext.cancel_event``
and normalizes failures into the ``{ok, error, code}`` contract used by
``WorkflowErrorCode``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from ai.core.workflow.context import RunContext
from ai.core.workflow.errors import WorkflowErrorCode


class WorkflowToolAdapter:
  """Adapt the full tool-handler map into a ``ToolRunner``.

  Construct once per workflow run (or once globally and reuse), then pass
  ``adapter.run`` as ``engine.set_tool_runner``.
  """

  def __init__(
    self,
    handlers: dict[str, Callable[..., Any]],
    *,
    ctx: RunContext | None = None,
  ) -> None:
    self._handlers = handlers
    self._ctx = ctx

  @classmethod
  def from_factory(
    cls,
    handlers_factory: Callable[[], dict[str, Callable[..., Any]]],
    *,
    ctx: RunContext | None = None,
  ) -> "WorkflowToolAdapter":
    """Build an adapter whose handler map is created lazily and then cached."""
    return cls(handlers_factory(), ctx=ctx)

  def tool_names(self) -> list[str]:
    return sorted(self._handlers.keys())

  def has_tool(self, name: str) -> bool:
    return name in self._handlers

  async def run(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Invoke ``name`` with ``args``, normalizing sync/async + errors."""
    handler = self._handlers.get(name)
    if handler is None:
      return {
        "ok": False,
        "error": f"tool '{name}' not found",
        "code": WorkflowErrorCode.TOOL_NOT_FOUND.value,
      }

    if self._ctx is not None:
      try:
        self._ctx.check_cancelled()
      except Exception as exc:
        return {
          "ok": False,
          "error": str(exc),
          "code": WorkflowErrorCode.CANCELLED.value,
        }

    try:
      if asyncio.iscoroutinefunction(handler):
        coro = handler(args)
        if self._ctx is not None and self._ctx.cancel_event is not None:
          done, pending = await asyncio.wait(
            {asyncio.ensure_future(coro)},
            return_when=asyncio.FIRST_COMPLETED,
          )
          for p in pending:
            p.cancel()
          if not done:
            return {
              "ok": False,
              "error": "cancelled before completion",
              "code": WorkflowErrorCode.CANCELLED.value,
            }
          result = next(iter(done)).result()
        else:
          result = await coro
      else:
        result = handler(args)
    except asyncio.CancelledError:
      return {
        "ok": False,
        "error": "cancelled",
        "code": WorkflowErrorCode.CANCELLED.value,
      }
    except Exception as exc:
      return {
        "ok": False,
        "error": str(exc),
        "code": WorkflowErrorCode.TOOL_FAILED.value,
      }

    if isinstance(result, dict) and "ok" not in result:
      # Coerce to the standard contract without dropping original fields.
      return {"ok": True, **result}
    return result


__all__ = ["WorkflowToolAdapter"]