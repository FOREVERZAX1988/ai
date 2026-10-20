#!/usr/bin/env python3
"""Check the upstream-divergence registry against another upstream tip.

For every entry in ai/docs/upstream_divergence_registry.json this prints one
line and, more importantly, checks the two things a re-baseline silently
breaks:

  1. `upstream_intent_present` -- literal snippets of the upstream change that
     must still exist inside *our* file. Missing => the upstream fix was dropped.
  2. `expect_diff` -- whether our file is supposed to differ from upstream. A
     file that was supposed to differ but now matches upstream means our patch
     disappeared (WARN); a file that was supposed to match but differs is FAIL.

Usage:
  python3 ai/scripts/upstream_divergence_check.py                    # HEAD vs upstream/test
  python3 ai/scripts/upstream_divergence_check.py --ref upstream/test --side worktree
  python3 ai/scripts/upstream_divergence_check.py --only stopping_controller.py

Exit code 0 = every entry as expected, 1 = at least one FAIL/WARN.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "ai" / "docs" / "upstream_divergence_registry.json"


def _git(*args: str) -> subprocess.CompletedProcess:
  return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)


def upstream_text(ref: str, path: str) -> str | None:
  r = _git("show", f"{ref}:{path}")
  return r.stdout if r.returncode == 0 else None


def ours_text(side: str, path: str) -> str | None:
  if side == "worktree":
    p = ROOT / path
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else None
  r = _git("show", f"HEAD:{path}")
  return r.stdout if r.returncode == 0 else None


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--ref", default="upstream/test")
  ap.add_argument("--side", default="HEAD", choices=("HEAD", "worktree"))
  ap.add_argument("--only", default=None, help="substring filter on the path")
  ap.add_argument("--json", action="store_true")
  args = ap.parse_args()

  registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
  rows, failures = [], 0
  for entry in registry["entries"]:
    path = entry["path"]
    if args.only and args.only not in path:
      continue
    up, mine = upstream_text(args.ref, path), ours_text(args.side, path)
    if up is None or mine is None:
      rows.append({"path": path, "state": "MISSING", "detail": f"upstream={up is not None} ours={mine is not None}"})
      failures += 1
      continue

    missing = [s for s in entry.get("upstream_intent_present", []) if s not in mine]
    differs = up != mine
    if missing:
      state, detail = "FAIL", "upstream intent missing: " + " | ".join(missing[:3])
    elif entry.get("expect_diff") and not differs:
      state, detail = "WARN", "expected to differ from upstream but is identical (patch lost?)"
    elif not entry.get("expect_diff") and differs:
      state, detail = "FAIL", "expected identical but differs"
    else:
      state, detail = "OK", "differs as designed" if differs else "identical as designed"
    failures += state != "OK"
    rows.append({"path": path, "verdict": entry.get("verdict"), "state": state, "detail": detail})

  if args.json:
    print(json.dumps({"ref": args.ref, "side": args.side, "rows": rows}, ensure_ascii=False, indent=2))
  else:
    print(f"registry: {REGISTRY.relative_to(ROOT)}   upstream ref: {args.ref}   ours: {args.side}")
    for r in rows:
      print(f"  {r['state']:5s} {r['path']}")
      if r["state"] != "OK":
        print(f"        {r['detail']}")
    print(f"  => {sum(r['state'] == 'OK' for r in rows)}/{len(rows)} as expected")
  return 0 if failures == 0 else 1


if __name__ == "__main__":
  sys.exit(main())
