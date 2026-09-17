#!/usr/bin/env python3
"""Standalone runner for post-patch verification probe (used by routes.py job worker).

Re-runs ``eps_patch.py probe`` and checks whether the telescope classification has
advanced to ``already_patched``. This is the safety net that confirms the flash
writer actually succeeded before the operator drives away.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make ``import ai.tools...`` work when invoked from outside the project root.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
  sys.path.insert(0, str(_PROJECT_ROOT))

from ai.tools.domains.secoc.eps_patch_tools import eps_patch_run_verify


def main() -> int:
  serial = sys.argv[1] if len(sys.argv) > 1 else ""
  result = eps_patch_run_verify(serial=serial, confirm=True)
  print(json.dumps(result, ensure_ascii=False))
  return 0 if result.get("verified") else 1


if __name__ == "__main__":
  raise SystemExit(main())