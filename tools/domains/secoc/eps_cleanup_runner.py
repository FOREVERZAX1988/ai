#!/usr/bin/env python3
"""Standalone runner for EPS backup cleanup (used by routes.py job worker).

Applies retention policy: delete backups older than max_age_days and
keep at most max_count recent entries. Never deletes the latest backup.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make ``import ai.tools...`` work when invoked from outside the project root.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
  sys.path.insert(0, str(_PROJECT_ROOT))

from ai.tools.domains.secoc.eps_patch_tools import eps_patch_cleanup_backups


def main() -> int:
  max_age_days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
  max_count = int(sys.argv[2]) if len(sys.argv) > 2 else 20
  dry_run = "--dry-run" in sys.argv
  result = eps_patch_cleanup_backups(max_age_days=max_age_days, max_count=max_count, dry_run=dry_run)
  print(json.dumps(result, ensure_ascii=False))
  return 0 if result.get("ok") else 1


if __name__ == "__main__":
  raise SystemExit(main())