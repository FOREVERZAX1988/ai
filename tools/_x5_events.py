#!/usr/bin/env python3
"""_x5_events.py <route> <segidx> <lo> <hi> —— 事件时间线 v3（含视觉原始 lead / 报警文本）。"""
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


def g(x, s, n):
  return (int.from_bytes(x, 'little') >> s) & ((1 << n) - 1)


def emit(rt, key, val):
  if prev.get(key) != val:
    prev[key] = val
    print(f"{rt:7.2f} {key:5s} {val}", flush=True)


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
        emit(rt, 'F2' if m.src == 2 else 'O2', ((x[3] | (x[4] << 8)) & 0x3FF, (x[5] >> 6) & 3, g(x, 44, 2)))
      elif m.address == 269:
        emit(rt, 'F5' if m.src == 2 else 'O5', (g(x, 57, 3), round(g(x, 32, 11) * 0.005 - 7.22, 1),
                                                g(x, 62, 1), g(x, 43, 1), g(x, 61, 1)))
      elif m.address == 267 and len(x) >= 3:
        emit(rt, 'FL' if m.src == 2 else 'OL', ((x[1] >> 5) & 1, (x[2] >> 0) & 1, (x[2] >> 3) & 1))
    continue
  if w == 'modelV2':
    try:
      ld = e.modelV2.leadsV3[0]
      emit(rt, 'MV', (round(ld.prob, 2), round(ld.x[0], 1), round(ld.v[0], 1)))
    except Exception:
      pass
  elif w == 'radarState':
    ld = e.radarState.leadOne
    emit(rt, 'RD', (int(ld.present), round(ld.dRel, 1), round(ld.vRel, 1), round(ld.vLead, 1)))
  elif w == 'carControl':
    emit(rt, 'CC', (round(e.carControl.actuators.accel, 1), int(e.carControl.longActive)))
  elif w == 'controlsState':
    emit(rt, 'CT', (str(e.controlsState.longControlState).split('.')[-1],))
  elif w == 'selfdriveState':
    ss = e.selfdriveState
    emit(rt, 'SS', (int(ss.enabled), str(ss.state).split('.')[-1][:10], str(getattr(ss, 'alertText1', ''))[:30]))
  elif w == 'carState':
    cs = e.carState
    emit(rt, 'CS', (int(cs.standstill), int(cs.gasPressed), int(cs.brakePressed),
                    int(cs.cruiseState.enabled), round(cs.cruiseState.speed * 3.6, 1), int(cs.accFaulted)))
    emit(rt, 'v', (round(cs.vEgo * 2) / 2.0,))
