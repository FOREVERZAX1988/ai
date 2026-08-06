#!/usr/bin/env python3
"""Verify architecture packages and compatibility shims import cleanly."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

MODULES = [
  "ai.core.llm.client",
  "ai.core.chat.runner",
  "ai.core.sync.hub",
  "ai.core.sync.protocol",
  "ai.core.workspace.persona",
  "ai.services.cabana",
  "ai.services.cabana.qlog_finder",
  "ai.services.tsk",
  "ai.infra.auth.web",
  "ai.tools.registry",
  "ai.tools.executor",
  "ai.tools.domains.core.diagnostics_tools",
  "ai.integration.fork",
  # shims
  "ai.client",
  "ai.chat_runner",
  "ai.sync_hub",
  "ai.cabana",
  "ai.model_accounts",
]

HANDLERS = [
  "ai.server.handlers.chat_handlers",
  "ai.server.handlers.config_handlers",
  "ai.server.handlers.api",
]


def main() -> int:
  failed = []
  for name in MODULES + HANDLERS:
    try:
      importlib.import_module(name)
      print(f"ok  {name}")
    except Exception as e:
      print(f"FAIL {name}: {e}")
      failed.append(name)
  if failed:
    print(f"\n{len(failed)} failed")
    return 1
  print("\nall imports ok")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
