#!/usr/bin/env python3
"""Diagnostic replay: run openpilot's FULL daemon chain on a recorded route.

Why this exists
---------------
Onroad preview only starts camerad + modeld. selfdrived, locationd, paramsd,
controlsd and plannerd are all gated on deviceState.started, so they never run
parked -- which means bugs that produce a selfdriveState alert (the "temporary
fault", commIssue, steering-misalignment, stopping) cannot be reproduced or
verified without driving.

This tool feeds a recorded route back into openpilot so the whole chain runs
on real data, on the bench, while guaranteeing nothing can drive the car.

Safety model (never weaken these)
---------------------------------
1. manager must be started with NOBOARD=1: pandad is not started at all, so
   nothing subscribes to `sendcan` and calls panda.can_send().
2. This tool asserts at startup (and re-checks periodically) that no real
   pandad process is alive. If one appears, it exits immediately.
3. It never opens /dev/panda, never touches USB, never publishes `sendcan`.
4. pandaStates is synthesized with ignitionLine=True so hardwared sets
   started=True (that is the switch the full daemon chain is gated on), but
   with controlsAllowed=False so nothing downstream considers itself engaged.
5. All msgq traffic lives under an OPENPILOT_PREFIX, isolated from any real
   process. Run it via diag_replay.sh, which sets the prefix and NOBOARD.

What it publishes
-----------------
  * can        -- verbatim CAN frames from the rlog (the car's own DBC, no
                  synthetic Honda frames), replayed at the recorded cadence
  * pandaStates-- synthesized: ignition on, controls disallowed
  * carParams  -- restored from the rlog (so fingerprint/safety match the car)

Camera frames come from `tools/replay --wide-road --qcam` under the same
prefix, started by diag_replay.sh. This tool does not provide visionipc frames.

Usage
-----
  ./diag_replay.sh <route_dir>              # e.g. .../00000031--...--0
  ./diag_replay.sh <route_dir> --loop --rate 1.0

`route_dir` must contain rlog.zst (one segment). For a whole route, point at
the parent and use tools/replay's segment selection instead.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

import openpilot.cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.selfdrive.pandad.pandad_api_impl import can_list_to_can_capnp


PANDA_STATES_HZ = 2


def assert_no_pandad() -> None:
  """Hard safety gate. A live pandad means sendcan could reach a real panda."""
  try:
    out = subprocess.run(['pgrep', '-af', 'pandad'], capture_output=True, text=True).stdout
  except Exception:
    return
  lines = [l for l in out.splitlines()
           if 'pgrep' not in l and 'diag_replay' not in l]
  if lines:
    raise SystemExit('REFUSING TO RUN: a real pandad is alive (%s).\n'
                     'Diagnostic replay requires NOBOARD=1 (pandad not started).\n'
                     'Stop comma and relaunch via diag_replay.sh.' % lines[:3])


def make_panda_states(car_params):
  """Synthesize one pandaStates message: ignition on, controls disallowed.

  Built as one dict assignment, the way simulated_car.py does it -- pandaState
  is a fixed-size capnp struct whose optional/enum fields are not individually
  settable on a DynamicStructReader element.
  """
  dat = messaging.new_message('pandaStates', 1)
  # CRITICAL: new_message() defaults valid=False. hardwared's SubMaster only
  # treats ignition/started updates from a VALID pandaStates; without this the
  # whole onroad daemon chain (card/controlsd/selfdrived) never starts and the
  # tool looks hung. The official simulated_car.py sets dat.valid = True too.
  dat.valid = True
  state = {
    'ignitionLine': True,
    'pandaType': 'blackPanda',
    'controlsAllowed': False,
    'controlsAllowedLateral': False,
    'controlsAllowedLongitudinal': False,
  }
  try:
    state['safetyModel'] = 'silent' if car_params is None else str(car_params.safetyConfigs[0].safetyModel)
    if car_params is not None:
      state['alternativeExperience'] = int(car_params.alternativeExperience)
  except Exception:
    state['safetyModel'] = 'silent'
  dat.pandaStates[0] = state
  return dat


class _CPSnapshot:
  """Plain-Python copy of the only CarParams fields make_panda_states() reads.

  capnp readers are only valid inside their `with` context; returning one from
  load_car_params() used to hand make_panda_states a dead reader. Snapshot the
  two fields we need so the caller can hold it for the whole replay.
  """
  def __init__(self, safety_model: str, alternative_experience: int):
    self.safetyConfigs = [_CPSnapshot._SafetyConfig(safety_model)]
    self.alternativeExperience = alternative_experience

  class _SafetyConfig:
    def __init__(self, safety_model: str):
      self.safetyModel = safety_model


def _snapshot_cp(cp) -> _CPSnapshot:
  return _CPSnapshot(str(cp.safetyConfigs[0].safetyModel), int(cp.alternativeExperience))


def _pin_platform(params, cp) -> str:
  """Write CarPlatformBundle so card.py:195 skips live VAG UDS fingerprinting.

  Without this, get_car() runs VIN/FW queries against the replayed CAN and
  blocks forever (there is no live diagnostic ECU to answer on the bus).
  """
  fingerprint = str(cp.carFingerprint)
  bundle = {'platform': fingerprint, 'brand': str(cp.brand), 'name': fingerprint}
  params.put('CarPlatformBundle', bundle, block=True)
  return fingerprint


def load_car_params(segment=None):
  """Recover CarParams + pin the platform, from the rlog or (fallback) params.

  Sources, in order of authority:
    1. the segment's rlog (what the car actually was) -- ideal, has carParams
    2. params CarParams (seeded by a prior replay)
    3. params CarParamsPersistent (survives reboots; VAG has VIN + FW in it)

  The critical side effect -- regardless of source -- is writing
  CarPlatformBundle. That is what keeps card's get_car() from issuing live UDS
  VIN/FW queries on the replayed (answer-less) CAN bus.
  """
  from cereal import log
  params = Params()
  # 1) from the rlog (authoritative: what the car actually was)
  if segment:
    try:
      from openpilot.tools.lib.logreader import LogReader
      rlog = os.path.join(segment, 'rlog.zst')
      for msg in LogReader(rlog):
        if msg.which() == 'carParams':
          cp = msg.carParams
          # msg.carParams is a CarParams struct; card reads CarParamsPersistent
          # with car.CarParams.from_bytes(), i.e. it expects the STRUCT bytes,
          # not the enclosing log.Event bytes. Writing the Event here makes
          # card crash at `cp.carVin` with a capnp layout mismatch.
          cp_bytes = cp.as_builder().to_bytes()
          # CarParams (the live param) is Event-wrapped; Persistent is the bare struct.
          ev = log.Event.new_message()
          ev.carParams = cp
          params.put('CarParams', ev.to_bytes())
          params.put('CarParamsPersistent', cp_bytes)
          fingerprint = _pin_platform(params, cp)
          print(f'  CarParams restored from rlog (platform pinned: {fingerprint})', flush=True)
          return _snapshot_cp(cp)
    except Exception as e:
      print(f'  CarParams-from-rlog failed: {e}', flush=True)
  # 2) fallback: params CarParams (seeded by replay or a prior run)
  try:
    raw = params.get('CarParams', block=False)
    if raw is not None:
      with log.Event.from_bytes(raw) as ev:
        cp = ev.carParams
        # keep Persistent consistent with the struct form card expects
        params.put('CarParamsPersistent', cp.as_builder().to_bytes())
        fingerprint = _pin_platform(params, cp)
        print(f'  CarParams restored from params CarParams (platform pinned: {fingerprint})', flush=True)
        return _snapshot_cp(cp)
  except Exception as e:
    print(f'  CarParams-from-params failed: {e}', flush=True)
  # 3) last resort: CarParamsPersistent. Short/parking segments have no
  #    carParams in the rlog and a fresh boot clears CarParams, but Persistent
  #    survives reboots. On VAG it carries VIN + 9 FW entries (measured), enough
  #    to both pin the platform AND satisfy card's cached-params branch.
  try:
    from opendbc.car.structs import car
    raw = params.get('CarParamsPersistent', block=False)
    if raw is None:
      return None
    with car.CarParams.from_bytes(raw) as cp:
      snap = _snapshot_cp(cp)
      fingerprint = _pin_platform(params, cp)
    print(f'  CarParams restored from persistent (platform pinned: {fingerprint})', flush=True)
    return snap
  except Exception as e:
    print(f'  CarParams-from-persistent failed: {e}', flush=True)
    return None


def iter_can(segment: str, loop: bool):
  """Yield (relative_time_s, can_message) from the segment's rlog, in order."""
  from openpilot.tools.lib.logreader import LogReader
  rlog = os.path.join(segment, 'rlog.zst')
  if not os.path.exists(rlog):
    raise SystemExit(f'no rlog.zst in {segment}')
  while True:
    t0 = None
    for msg in LogReader(rlog):
      if msg.which() != 'can':
        continue
      t = msg.logMonoTime / 1e9
      if t0 is None:
        t0 = t
      yield (t - t0), msg
    if not loop:
      return


def seed_startup_params() -> None:
  """Force every hardwared startup/onroad gate that can keep the bench offroad.

  hardwared only sets deviceState.started (the switch the whole onroad daemon
  chain -- card/controlsd/selfdrived/plannerd -- is gated on) when *all* startup
  and onroad conditions pass. set_params_enabled() covers some of them but not
  the sunnypilot-only HasAcceptedTermsSP, and a params migration can rewrite it
  to a stale value. Seed from the running build's own version constants so the
  comparison in hardwared.py:360-361 can never fail.
  """
  from openpilot.common.version import terms_version, terms_version_sp, training_version
  p = Params()
  p.put('HasAcceptedTerms', terms_version, block=True)
  p.put('HasAcceptedTermsSP', terms_version_sp, block=True)
  p.put('CompletedTrainingVersion', training_version, block=True)
  p.put_bool('OpenpilotEnabledToggle', True, block=True)
  p.put_bool('OffroadMode', False, block=True)
  p.put_bool('OnroadCycleRequested', False, block=True)


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument('segment', help='segment dir containing rlog.zst')
  ap.add_argument('--loop', action='store_true', help='loop the segment')
  ap.add_argument('--rate', type=float, default=1.0, help='playback speed (1.0 = realtime)')
  args = ap.parse_args()

  if os.getenv('NOBOARD') is None:
    raise SystemExit('REFUSING TO RUN without NOBOARD=1. Use diag_replay.sh.')
  assert_no_pandad()

  print('diag_replay: full-chain diagnostic replay', flush=True)
  print(f'  segment={args.segment} loop={args.loop} rate={args.rate}', flush=True)
  print('  NOBOARD=1, no pandad, publishing can + synthetic pandaStates only', flush=True)

  # OpenpilotPrefix (C++) creates the msgq dir; the Python side only setenv's,
  # so make the isolated directory ourselves before opening any socket.
  prefix = os.getenv('OPENPILOT_PREFIX')
  if prefix:
    os.makedirs(f'/dev/shm/msgq_{prefix}', exist_ok=True)

  seed_startup_params()
  pm = messaging.PubMaster(['can', 'pandaStates'])
  cp = load_car_params(args.segment)
  print(f'  CarParams: {"loaded" if cp is not None else "NOT loaded (replay seeds it)"}', flush=True)

  # CAN cadence comes from the rlog timestamps below (the `target`/sleep), which
  # reproduce pandad's real ~100 Hz. Do NOT add a Ratekeeper here: an earlier
  # version used Ratekeeper(PANDA_STATES_HZ=2) at the bottom of this loop and
  # silently throttled CAN to 2 Hz -- card's can_fingerprint then needed ~100 s
  # to reach FRAME_FINGERPRINT (200 frames) and looked like it hung on UDS.
  wall = None
  last_ps = 0.0
  check_t = 0.0
  can_count = 0
  for rel, msg in iter_can(args.segment, args.loop):
    if wall is None:
      wall = time.monotonic()
    target = wall + rel / max(0.01, args.rate)
    delay = target - time.monotonic()
    if delay > 0:
      time.sleep(delay)

    # A can Event holds several frames; repackage them into the same wire form
    # pandad publishes. Values are verbatim from the recording.
    frames = [(f.address, f.dat, f.src) for f in msg.can]
    if frames:
      pm.send('can', can_list_to_can_capnp(frames))
      can_count += len(frames)

    # periodic safety re-check + synthetic pandaStates
    now = time.monotonic()
    if now - check_t > 1.0:
      assert_no_pandad()
      check_t = now
    if now - last_ps >= 1.0 / PANDA_STATES_HZ:
      pm.send('pandaStates', make_panda_states(cp))
      last_ps = now

  return 0


if __name__ == '__main__':
  sys.exit(main())
