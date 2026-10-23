#!/usr/bin/env python3
"""Check the upstream-divergence registry against another upstream tip.

Phase 0 -- the remote itself:
  `remote.upstream.fetch` must cover `refs/heads/*`. If it is pinned to one
  branch (this repo carried `+refs/heads/master-c3:...` for months) then
  `git fetch upstream` silently reports "already up to date" while `test` moves
  ahead -- that is how "上游无更新" was mis-judged. `--fix-fetch` repairs it.

Two phases, both driven by ai/docs/upstream_divergence_registry.json.

Phase 1 -- `entries` (files that differ on purpose):
  1. `upstream_intent_present` -- literal snippets of the upstream change that
     must still exist inside *our* file. Missing => the upstream fix was dropped.
  2. `expect_diff` -- whether our file is supposed to differ from upstream. A
     file that was supposed to differ but now matches upstream means our patch
     disappeared (WARN); a file that was supposed to match but differs is FAIL.

Phase 2 -- `upstream_pending_port.items` (upstream work we have NOT ported):
  Each item carries machine-checkable `probes` describing what "still not
  ported" looks like *right now*:
    path_absent             the file must not exist yet
    path_present            the file must still exist (upstream's change deleted it)
    symbol_absent           the needle must not appear in the file yet
    symbol_present          the needle must still appear (upstream's change removes it)
    submodule_not_ancestor  that upstream pin must not be an ancestor of the
                            submodule's HEAD yet
  A probe that no longer holds means we already ported it (or upstream moved):
  that is DRIFT -- go update the registry instead of trusting the list.

Usage:
  python3 ai/scripts/upstream_divergence_check.py                    # HEAD vs upstream/test
  python3 ai/scripts/upstream_divergence_check.py --ref upstream/test --side worktree
  python3 ai/scripts/upstream_divergence_check.py --only stopping_controller.py
  python3 ai/scripts/upstream_divergence_check.py --pending-only     # phase 2 only
  python3 ai/scripts/upstream_divergence_check.py --json

Exit code 0 = everything as expected, 1 = at least one FAIL/WARN/DRIFT.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "ai" / "docs" / "upstream_divergence_registry.json"


def _git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
  return subprocess.run(["git", "-C", str(cwd or ROOT), *args], capture_output=True, text=True)


def upstream_text(ref: str, path: str) -> str | None:
  r = _git("show", f"{ref}:{path}")
  return r.stdout if r.returncode == 0 else None


def ours_text(side: str, path: str) -> str | None:
  if side == "worktree":
    p = ROOT / path
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else None
  r = _git("show", f"HEAD:{path}")
  return r.stdout if r.returncode == 0 else None


def _file_text(rel: str) -> str | None:
  p = ROOT / rel
  return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else None


def run_probe(probe: dict) -> tuple[str, str]:
  """Return (state, detail). state in {OK, DRIFT, SKIP}."""
  kind, target, needle = probe.get("kind"), probe.get("target", ""), probe.get("needle")

  if kind == "path_absent":
    if (ROOT / target).exists():
      return "DRIFT", f"path now exists (already ported?): {target}"
    return "OK", f"absent: {target}"

  if kind == "path_present":
    if not (ROOT / target).exists():
      return "DRIFT", f"path is gone (already ported?): {target}"
    return "OK", f"still present: {target}"

  if kind in ("symbol_absent", "symbol_present"):
    text = _file_text(target)
    if text is None:
      return ("OK" if kind == "symbol_absent" else "DRIFT"), f"file missing: {target}"
    found = needle in text
    if kind == "symbol_absent":
      return ("DRIFT", f"symbol appeared (already ported?): {needle}") if found else ("OK", f"no {needle}")
    return ("OK", f"still has {needle}") if found else ("DRIFT", f"symbol gone (already ported?): {needle}")

  if kind == "submodule_not_ancestor":
    sub = ROOT / target
    if not (sub / ".git").exists():
      return "SKIP", f"submodule not checked out: {target}"
    known = _git("cat-file", "-t", needle, cwd=sub)
    if known.returncode != 0:
      return "SKIP", f"pin unknown locally ({needle[:10]}) -- git fetch the submodule"
    anc = _git("merge-base", "--is-ancestor", needle, "HEAD", cwd=sub)
    head = _git("rev-parse", "--short", "HEAD", cwd=sub).stdout.strip()
    if anc.returncode == 0:
      return "DRIFT", f"pin {needle[:10]} IS in {target}@{head} (already ported?)"
    return "OK", f"pin {needle[:10]} not in {target}@{head}"

  return "SKIP", f"unknown probe kind: {kind}"


FETCH_REMOTE = "upstream"
FETCH_SPEC = f"+refs/heads/*:refs/remotes/{FETCH_REMOTE}/*"


def check_fetch_spec(remote: str = FETCH_REMOTE) -> tuple[bool, list[str]]:
  """Is `remote.<remote>.fetch` a wildcard refspec (so every branch is fetched)?"""
  r = _git("config", "--get-all", f"remote.{remote}.fetch")
  specs = [s.strip() for s in r.stdout.splitlines() if s.strip()]
  wildcard = f"refs/heads/*:refs/remotes/{remote}/*"
  return any(s.lstrip("+").endswith(wildcard) for s in specs), specs


def phase_entries(args, registry: dict) -> tuple[list[dict], int]:
  rows, failures = [], 0
  for entry in registry["entries"]:
    path = entry["path"]
    if args.only and args.only not in path:
      continue
    if entry.get("local_only"):
      # 本树独有的文件（上游没有对应物）。拿 upstream_text 比会把 MISSING 当失败，
      # 于是每次同步都被当成「上游删了/我们丢了」——实际是结构差异。
      mine = ours_text(args.side, path)
      up = upstream_text(args.ref, path)
      if mine is None:
        rows.append({"path": path, "verdict": entry.get("verdict"), "state": "FAIL", "detail": "local-only file missing in our tree"})
        failures += 1
      elif up is not None:
        rows.append({"path": path, "verdict": entry.get("verdict"), "state": "OK",
                     "detail": "local-only, but upstream now has a file here too -- re-audit"})
      else:
        rows.append({"path": path, "verdict": entry.get("verdict"), "state": "OK",
                     "detail": "local-only, no upstream counterpart (as recorded)"})
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
  return rows, failures


def phase_pending(registry: dict) -> tuple[list[dict], int]:
  section = registry.get("upstream_pending_port") or {}
  items = section.get("items", [])
  rows, failures, skipped = [], 0, 0
  for item in items:
    bad, notes = [], []
    for probe in item.get("probes", []):
      state, detail = run_probe(probe)
      if state == "DRIFT":
        bad.append(detail)
      elif state == "SKIP":
        skipped += 1
        notes.append(detail)
    state = "DRIFT" if bad else "OK"
    failures += bool(bad)
    rows.append({
      "commit": item["commit"][:10],
      "subject": item.get("subject", ""),
      "status": item.get("status", ""),
      "state": state,
      "detail": " | ".join(bad) if bad else "; ".join(notes),
    })
  return rows, failures


def phase_deferred_hooks(registry: dict) -> tuple[list[dict], int]:
  """deferred_hooks 以前根本没跑过探针：钩子都落地了、status 还写着 deferred，checker 也照样全绿。

  现在把两个方向都断言上，并且先查 status 与 probe.kind 是否自洽：
    deferred -> probe.kind 必须是 symbol_absent（符号还没出现）
    ported   -> probe.kind 必须是 symbol_present（符号必须在位）
  照旧名的重构或「落地了但忘了标 done」都会在这里变红。
  """
  section = registry.get("upstream_pending_port") or {}
  hooks = section.get("deferred_hooks") or []
  rows, failures = [], 0
  for hook in hooks:
    status = hook.get("status", "")
    probe = hook.get("probe") or {}
    kind = probe.get("kind", "")
    expected_kind = {"deferred": "symbol_absent", "ported": "symbol_present"}.get(status)
    if expected_kind is None:
      bad = [f"unknown status {status!r}"]
    elif kind != expected_kind:
      bad = [f"status={status} expects probe kind {expected_kind}, registry has {kind}"]
    else:
      state, detail = run_probe(probe)
      bad = [] if state == "OK" else [detail]
    failures += bool(bad)
    rows.append({
      "commit": (hook.get("from_commit") or "")[:10],
      "what": hook.get("what", ""),
      "status": status,
      "state": "DRIFT" if bad else "OK",
      "detail": " | ".join(bad),
    })
  return rows, failures


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--ref", default="upstream/test")
  ap.add_argument("--side", default="HEAD", choices=("HEAD", "worktree"))
  ap.add_argument("--only", default=None, help="substring filter on the path (phase 1)")
  ap.add_argument("--fix-fetch", action="store_true", help=f"write {FETCH_SPEC} into remote.{FETCH_REMOTE}.fetch")
  ap.add_argument("--skip-fetch-check", action="store_true", help="do not verify the remote refspec (phase 0)")
  ap.add_argument("--pending-only", action="store_true", help="only phase 2 (unported upstream work)")
  ap.add_argument("--entries-only", action="store_true", help="only phase 1 (diverged files)")
  ap.add_argument("--json", action="store_true")
  args = ap.parse_args()

  if args.fix_fetch:
    _git("config", f"remote.{FETCH_REMOTE}.fetch", FETCH_SPEC)
    print(f"wrote remote.{FETCH_REMOTE}.fetch = {FETCH_SPEC}")

  registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
  fetch_state, fetch_detail = "SKIP", "fetch check skipped"
  if not args.skip_fetch_check:
    ok, specs = check_fetch_spec()
    if ok:
      fetch_state, fetch_detail = "OK", f"wildcard refspec in place ({len(specs)} spec(s))"
    else:
      fetch_state = "WARN"
      found = "; ".join(specs) or "none"
      fetch_detail = f"remote.upstream.fetch lacks refs/heads/* (found: {found}) -- git fetch can miss branches; use --fix-fetch"
  entries, pending, hooks, failures = [], [], [], 0
  failures += fetch_state == "WARN"
  if not args.pending_only:
    entries, f1 = phase_entries(args, registry)
    failures += f1
  if not args.entries_only:
    pending, f2 = phase_pending(registry)
    hooks, f3 = phase_deferred_hooks(registry)
    failures += f2 + f3

  if args.json:
    print(json.dumps({"ref": args.ref, "side": args.side, "fetch": {"state": fetch_state, "detail": fetch_detail},
                      "entries": entries, "pending": pending, "deferred_hooks": hooks},
                     ensure_ascii=False, indent=2))
    return 0 if failures == 0 else 1

  print(f"registry: {REGISTRY.relative_to(ROOT)}   upstream ref: {args.ref}   ours: {args.side}")
  print(f"  [phase 0] remote.{FETCH_REMOTE}.fetch  {fetch_state}")
  if fetch_state != "OK":
    print(f"            {fetch_detail}")
  if entries:
    print("  [phase 1] 有意分叉的文件")
    for r in entries:
      print(f"    {r['state']:7s} {r['path']}")
      if r["state"] != "OK":
        print(f"            {r['detail']}")
    print(f"    => {sum(r['state'] == 'OK' for r in entries)}/{len(entries)} as expected")
  if pending:
    print("  [phase 2] 上游已实现、我们未移植")
    for r in pending:
      print(f"    {r['state']:7s} {r['commit']} {r['status']:10s} {r['subject'][:70]}")
      if r["state"] != "OK" or r["detail"]:
        print(f"            {r['detail']}")
    print(f"    => {sum(r['state'] == 'OK' for r in pending)}/{len(pending)} still unported as recorded")
  if hooks:
    print("  [phase 3] 已推迟钩子（status 与探针必须自洽）")
    for r in hooks:
      print(f"    {r['state']:7s} {r['commit']} {r['status']:8s} {r['what'][:60]}")
      if r["state"] != "OK":
        print(f"            {r['detail']}")
    print(f"    => {sum(r['state'] == 'OK' for r in hooks)}/{len(hooks)} consistent")
  return 0 if failures == 0 else 1


if __name__ == "__main__":
  sys.exit(main())
