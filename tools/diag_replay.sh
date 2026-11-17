#!/usr/bin/env bash
# Diagnostic replay: run openpilot's full daemon chain on a recorded route,
# safely, on the bench. See diag_replay.py for the design and safety model.
#
# Usage:
#   ./diag_replay.sh <segment_dir> [--loop] [--rate 1.0]
# e.g.
#   ./diag_replay.sh /data/media/0/realdata/00000031--b7b6c905ad--23 --loop
#
# Press Ctrl-C to stop. Nothing here can drive the car: NOBOARD=1 means manager
# never starts pandad, so no process sends can_send() to a real panda.

set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <segment_dir> [--loop] [--rate 1.0]" >&2
  exit 2
fi
SEGMENT="$1"; shift

# --- safety: absolutely no real panda ------------------------------------
# manager holds /dev/shm/openpilot_manager.lock (a global singleton, NOT
# prefix-scoped). If the normal comma service is up, our manager would silently
# return at main() and this whole tool would do nothing. Worse, two managers
# fight over publisher endpoints and cause the exact "进程间通信问题" cascade
# this tool exists to debug. So require comma stopped, up front.
if systemctl is-active comma >/dev/null 2>&1; then
  echo "REFUSING: the normal comma service is running (holds the manager singleton lock)." >&2
  echo "  Stop it first:  sudo systemctl stop comma" >&2
  echo "  After the diagnostic, restore it:  sudo systemctl start comma" >&2
  exit 1
fi
if pgrep -af pandad | grep -v diag_replay >/dev/null 2>&1; then
  echo "REFUSING: pandad is running. Stop comma first: sudo systemctl stop comma" >&2
  exit 1
fi

# Isolate ALL msgq/visionipc/params traffic from any real process.
export OPENPILOT_PREFIX="${OPENPILOT_PREFIX:-diag}"
export NOBOARD=1                 # manager skips pandad -> sendcan is a dead letter
export SIMULATION=1
export SKIP_FW_QUERY=1
export PASSIVE=0
# manager/process.py launches every daemon with `Popen(['python', '-m', ...])`.
# A bare shell has only python3, so daemons die with FileNotFoundError and
# manager silently gives up. The normal comma service gets `python` from the
# venv; we must supply it too. Measured 2026-11-17.
export PATH="/usr/local/venv/bin:$PATH"

# Block processes that would touch hardware, need the cloud, or conflict with
# the messages replay/this tool publish. camerad is replaced by replay's
# VisionIpcServer (when built); pandad is already skipped by NOBOARD.
# The onroad control chain (card/controlsd/selfdrived/plannerd/radard) is blocked
# from manager and launched explicitly below: on a bench hardwared never sets
# deviceState.started (its SubMaster.frame never advances without a real panda),
# so manager's `only_onroad` gate would never start them. These daemons do NOT
# check started themselves -- they just consume CAN/pandaStates/carParams, which
# we feed -- so starting them directly reproduces the full onroad behavior.
# updated is blocked: on a bench it loops on the safe-staging overlay lock
# ("couldn't get overlay lock") and its restart churn makes deviceState.started
# flap, which destabilizes the whole replay. Nothing here needs OTA updates.
export BLOCK="${BLOCK:-},camerad,loggerd,encoderd,micd,logmessaged,manage_athenad,manage_sunnylinkd,uploader,updated,card,controlsd,selfdrived,plannerd,radard,radard_dpath"

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd )"
ROOT="$( cd "$DIR/../.." >/dev/null && pwd )"
cd "$ROOT"

# The venv's `python` is only /usr/bin/python3.12 -- it does not know where the
# openpilot / msgq / opendbc source trees live. manager launches daemons with a
# bare `python`, and diag_replay.py imports openpilot.cereal too, so without
# PYTHONPATH they all die with ModuleNotFoundError while manager silently gives
# up. Measured 2026-11-17. All three source trees are siblings under $ROOT.
export PYTHONPATH="$ROOT/msgq_repo:$ROOT/openpilot:$ROOT/opendbc_repo:$ROOT${PYTHONPATH:+:$PYTHONPATH}"

echo "=== diag_replay safety ===" >&2
echo "  prefix=$OPENPILOT_PREFIX NOBOARD=$NOBOARD (pandad will NOT start)" >&2
echo "  segment=$SEGMENT" >&2
echo "  PYTHONPATH=$PYTHONPATH" >&2
echo "  Ctrl-C to stop" >&2

# 1) replay (OPTIONAL): publishes camera frames via visionipc. Only needed for
#    modeld/vision daemons. The C++ binary is not always built on a device; the
#    core daemon chain (card, controlsd, selfdrived, plannerd) and the whole
#    selfdriveState alert path do NOT need camera frames. If the binary is
#    missing, skip it and run the rest -- that is enough to reproduce the
#    "temporary fault" / commIssue / no-stop bugs this tool targets.
#    CarParams no longer depends on replay: diag_replay.py recovers it from the
#    rlog or CarParamsPersistent.
REPLAY_PID=""
REPLAY_BIN="$ROOT/openpilot/tools/replay/replay"
BLOCKED="can,pandaStates,carControl,carControlSP,controlsState,selfdriveState,modelV2,longitudinalPlan,deviceMotion,liveLocationKalman,vehicleParameters,radarState,sendcan"
if [ -x "$REPLAY_BIN" ]; then
  "$REPLAY_BIN" "$SEGMENT" \
    --prefix="$OPENPILOT_PREFIX" --wide-road --qcam \
    --block="$BLOCKED" &
  REPLAY_PID=$!
  echo "  replay: camera frames ON ($REPLAY_BIN)" >&2
else
  echo "  replay binary not built -> CAMERA-LESS MODE (modeld idles; CAN/daemon chain still runs)" >&2
fi

# 2) CAN + pandaStates feeder (started=True switch, controls disallowed)
python3 "$DIR/diag_replay.py" "$SEGMENT" "$@" &
FEEDER_PID=$!

ONROAD_PIDS=()
cleanup() {
  echo "diag_replay: stopping..." >&2
  [ -n "$REPLAY_PID" ] && kill "$REPLAY_PID" 2>/dev/null || true
  kill "$FEEDER_PID" 2>/dev/null || true
  [ -n "${MGR_PID:-}" ] && kill "$MGR_PID" 2>/dev/null || true
  [ "${#ONROAD_PIDS[@]}" -gt 0 ] && kill "${ONROAD_PIDS[@]}" 2>/dev/null || true
  [ -n "$REPLAY_PID" ] && wait "$REPLAY_PID" 2>/dev/null || true
  wait "$FEEDER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# 3) manager: starts the offroad/support daemons against our isolated bus.
python3 -c "from openpilot.selfdrive.test.helpers import set_params_enabled; set_params_enabled()" 2>/dev/null || true
cd "$ROOT/openpilot/system/manager"
./manager.py &
MGR_PID=$!

# 4) onroad control chain, launched directly (see BLOCK note above).
#    Wait for the feeder to create the msgq endpoints and publish the first CAN
#    frames, then start card first (it seeds carState/carParams), followed by
#    the consumers. Each daemon gets the exact env manager would give it.
cd "$ROOT"
sleep 3
for MOD in \
  openpilot.selfdrive.car.card \
  openpilot.selfdrive.controls.controlsd \
  openpilot.selfdrive.selfdrived.selfdrived \
  openpilot.selfdrive.controls.plannerd \
  openpilot.selfdrive.controls.radard; do
  python3 -m "$MOD" &
  ONROAD_PIDS+=($!)
  echo "  onroad daemon: $MOD (pid $!)" >&2
done

trap 'cleanup' EXIT INT TERM
echo "=== diag_replay running; Ctrl-C to stop ===" >&2
wait
