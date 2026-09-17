#!/usr/bin/env python3
"""Standalone runner for EPS pre-patch snapshot (used by routes.py job worker).

This exists so the snapshot workflow can run inside the same polled job
machinery as telescope_probe and patch_probe. It re-runs eps_patch.py probe
and archives the resulting sector backups under artifacts/snapshots/ without
disturbing the existing probe backup used by patch/restore.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Make ``import ai.tools...`` work when invoked from outside the project root.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
  sys.path.insert(0, str(_PROJECT_ROOT))

from ai.tools.domains.secoc.eps_patch_tools import eps_patch_run_snapshot


def main() -> int:
  serial = sys.argv[1] if len(sys.argv) > 1 else ""
  result = eps_patch_run_snapshot(serial=serial, confirm=True)
  print(json.dumps(result, ensure_ascii=False))
  return 0 if result.get("ok") else 1


if __name__ == "__main__":
  raise SystemExit(main())
