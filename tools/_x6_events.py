#!/usr/bin/env python3
"""_x6_events.py <route> <segidx> <lo> <hi> —— 事件时间线 v4（MV/RD 量化到 0.5m）。"""
import glob
import os
import sys

sys.path.insert(0, '/data/openpilot')
from openpilot.tools.lib.logreader import LogReader

route, segidx, lo, hi = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
paths = sorted(glob.glob('/data/media/0/realdata/%s--*/rlog.zst' % route),
               key=lambda p: int(os.path.basename(os.path.dirname(p)).split('--')[-1]))
p = paths[segidx]
prev = {}
t0 = None


def emit(rt, key, val):
  if prev.get(key) != val:
    prev[key] = val
    print(f"{rt:7.2f} {key:5s} {val}", flush=True)


def q(x, step=0.5):
  return round(x / step) * step


for e in LogReader(p):
  t = e.logMonoTime / 1e9
  if t0 is None:
    t0 = t
  rt = t - t0
  if rt < lo or rt > hi:
    continue
  w = e.which()
  if w == 'can':
    for m in e.can:
      x = bytes(m.dat)
      if m.address == 780:
        emit(rt, 'F2' if m.src == 2 else 'O2', ((x[3] | (x[4] << 8)) & 0x3FF, (x[5] >> 6) & 3))
      elif m.address == 269:
        st = ((int.from_bytes(x, 'little') >> 57) & 7)
        emit(rt, 'F5' if m.src == 2 else 'O5',
             (st, round(((int.from_bytes(x, 'little') >> 32) & 0x7FF) * 0.005 - 7.22, 1),
              (int.from_bytes(x, 'little') >> 62) & 1, (int.from_bytes(x, 'little') >> 43) & 1))
      elif m.address == 267 and len(x) >= 3:
        emit(rt, 'FL' if m.src == 2 else 'OL', ((x[1] >> 5) & 1, (x[2] >> 3) & 1))
    continue
  if w == 'modelV2':
    try:
      ld = e.modelV2.leadsV3[0]
      emit(rt, 'MV', (round(ld.prob, 1), q(ld.x[0]), q(ld.v[0], 0.2)))
    except Exception:
      pass
  elif w == 'radarState':
    ld = e.radarState.leadOne
    emit(rt, 'RD', (int(ld.present), q(ld.dRel), q(ld.vRel, 0.2), q(ld.vLead, 0.2)))
  elif w == 'carControl':
    emit(rt, 'CC', (round(e.carControl.actuators.accel, 1), int(e.carControl.longActive)))
  elif w == 'controlsState':
    emit(rt, 'CT', (str(e.controlsState.longControlState).split('.')[-1],))
  elif w == 'selfdriveState':
    ss = e.selfdriveState
    emit(rt, 'SS', (int(ss.enabled), str(ss.state).split('.')[-1][:9], str(getattr(ss, 'alertText1', ''))[:26]))
  elif w == 'carState':
    cs = e.carState
    emit(rt, 'CS', (int(cs.standstill), int(cs.gasPressed), int(cs.brakePressed), int(cs.accFaulted)))
    emit(rt, 'v', (q(cs.vEgo, 0.25),))
