#!/usr/bin/env bash
# Safe full-suite entry for this fork.
#
# Why this wrapper exists (2026-11-11 full-suite post-mortem):
#   * A bare `python -m unittest discover` on the device wedged for 15+ min at
#     98% CPU in the car-interface parameterised suites (CANParser spam), read
#     NetworkManager connection files and wrote real /data/params keys.
#   * The hourly upstream automation merged, pushed and OTA-rebooted the device
#     while that suite was still running, invalidating the results and leaving
#     comma.service stopped mid-build.
#
# This wrapper uses the project's own parallel unittest runner
# (tools/test_runner.py; AGENTS.md: pytest was removed) and holds a lock file
# that the hourly automation checks before it touches the working tree.
#
# Usage:
#   ai/tools/full_test.sh                                   # whole openpilot/ tree
#   FULL_TEST_TARGETS="openpilot/common/tests" ai/tools/full_test.sh
#   ai/tools/full_test.sh -j4 -v --durations 20            # runner flags pass through
#
# On a live device, prefer running with comma stopped or limit workers (-j2);
# the runner itself is process-parallel and writes no device state by design.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOCK="/tmp/openpilot_full_test.lock"

if [ -e "$LOCK" ]; then
  echo "another full test is running (pid $(cat "$LOCK"))" >&2
  exit 1
fi
printf '%s\n' "$$" > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

cd "$ROOT"
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ] && [ -x /usr/local/venv/bin/python ]; then
  # On a comma device there is no repo-local .venv; fall back to the device venv
  # (numpy/capnp/raylib_nb live there). Plain `python3` has none of them, so a
  # full discovery would report hundreds of bogus collection errors.
  PY=/usr/local/venv/bin/python
fi
[ -x "$PY" ] || PY=python3
export HOME=/tmp/cleanhome
export PYTHONPATH="$ROOT:$ROOT/opendbc_repo:$ROOT/msgq_repo${PYTHONPATH:+:$PYTHONPATH}"

TARGETS="${FULL_TEST_TARGETS:-openpilot/}"

echo "full_test: pid $$ | targets: $TARGETS | lock: $LOCK" >&2
# shellcheck disable=SC2086
"$PY" tools/test_runner.py $TARGETS "$@" --json-output /tmp/openpilot_full_test_results.json
