#!/usr/bin/env python3
"""Verify architecture packages import cleanly (no root shims)."""

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
  "ai.core.workspace.store",
  "ai.services.cabana",
  "ai.services.cabana.replay",
  "ai.services.cabana.qlog_finder",
  "ai.services.tsk",
  "ai.services.panda",
  "ai.services.rag",
  "ai.infra.auth.web",
  "ai.infra.timezone",
  "ai.tools.registry",
  "ai.tools.executor",
  "ai.tools.domains.core.diagnostics_tools",
  "ai.tools.domains.tune.presets",
  "ai.tools.domains.vehicle.adaptation",
  "ai.integration.fork",
]

HANDLERS = [
  "ai.server.handlers.chat_handlers",
  "ai.server.handlers.config_handlers",
  "ai.server.handlers.api",
]

ROOT_PY = ["aid.py", "__init__.py"]


def main() -> int:
  failed = []
  for name in MODULES + HANDLERS:
    try:
      importlib.import_module(name)
      print(f"ok  {name}")
    except Exception as e:
      print(f"FAIL {name}: {e}")
      failed.append(name)

  root_files = sorted(p.name for p in ROOT.glob("*.py"))
  extra = [f for f in root_files if f not in ROOT_PY]
  if extra:
    print(f"\nunexpected root py files: {extra}")
    failed.extend(extra)

  if failed:
    print(f"\n{len(failed)} failed")
    return 1
  print("\nall imports ok")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
