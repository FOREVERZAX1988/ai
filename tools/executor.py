"""Tool execution with audit logging."""

from __future__ import annotations

import asyncio
import json
from typing import Any


def execute_tool(handlers: dict[str, Any], name: str, arguments: str) -> Any:
  handler = handlers.get(name)
  if handler is None:
    return {"ok": False, "error": f"Tool '{name}' not implemented"}
  try:
    args = json.loads(arguments) if arguments else {}
  except json.JSONDecodeError:
    return {"ok": False, "error": "Invalid tool arguments JSON"}
  try:
    result = handler(args)
    try:
      from ai.tools.audit_store import record_audit
      ok = True
      if isinstance(result, dict) and result.get("ok") is False:
        ok = False
      record_audit(action="tool_call", tool=name, detail={"args": args, "ok": ok}, ok=ok)
    except Exception:
      pass
    return result
  except Exception as e:
    return {"ok": False, "error": f"Tool execution failed: {e}"}


def _is_coroutine_handler(handler: Any) -> bool:
  import functools
  h = handler
  while isinstance(h, functools.partial):
    h = h.func
  return asyncio.iscoroutinefunction(h)


async def execute_tool_async(handlers: dict[str, Any], name: str, arguments: str) -> Any:
  handler = handlers.get(name)
  if handler is None:
    return {"ok": False, "error": f"Tool '{name}' not implemented"}
  try:
    args = json.loads(arguments) if arguments else {}
  except json.JSONDecodeError:
    return {"ok": False, "error": "Invalid tool arguments JSON"}
  try:
    # 2026-08-27: 同步 handler（如 run_shell_command 内部 subprocess.run）会阻塞 aiohttp
    # 事件循环（最长 timeout 秒），导致 aid HTTP 服务整体冻结。统一丢线程池执行。
    if _is_coroutine_handler(handler):
      result = await handler(args)
    else:
      loop = asyncio.get_running_loop()
      result = await loop.run_in_executor(None, handler, args)
    try:
      from ai.tools.audit_store import record_audit
      ok = True
      if isinstance(result, dict) and result.get("ok") is False:
        ok = False
      record_audit(action="tool_call", tool=name, detail={"args": args, "ok": ok}, ok=ok)
    except Exception:
      pass
    return result
  except Exception as e:
    return {"ok": False, "error": f"Tool execution failed: {e}"}
