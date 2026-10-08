#!/usr/bin/env python3
"""_x3_events.py <route> <segidx> <lo> <hi> —— 量化去抖事件时间线（含 LS_01 按键解码）。"""
import glob
import os
import sys

sys.path.insert(0, '/data/openpilot')
from openpilot.tools.lib.logreader import LogReader


def g(x, s, n):
  return (int.from_bytes(x, 'little') >> s) & ((1 << n) - 1)


route, segidx, lo, hi = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
paths = sorted(glob.glob('/data/media/0/realdata/%s--*/rlog.zst' % route),
               key=lambda p: int(os.path.basename(os.path.dirname(p)).split('--')[-1]))
p = paths[segidx]

prev = {}
t0 = None


def emit(rt, key, val):
  if prev.get(key) != val:
    prev[key] = val
    tag = {2: 'F', 0: 'O', 128: 'O'}.get(val[0] if isinstance(val, tuple) else None, '')
    print(f"{rt:7.2f} {key} {val}", flush=True)


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
        emit(rt, 'ACC02', ('F2' if m.src == 2 else 'O2', (x[3] | (x[4] << 8)) & 0x3FF,
                           (x[5] >> 6) & 3, g(x, 44, 2), g(x, 22, 2), round(g(x, 12, 10) * 0.32, 1)))
      elif m.address == 269:
        emit(rt, 'ACC05', ('F5' if m.src == 2 else 'O5', g(x, 57, 3),
                           round(g(x, 32, 11) * 0.005 - 7.22, 1), g(x, 16, 10),
                           g(x, 62, 1), g(x, 43, 1), g(x, 61, 1)))
      elif m.address == 267 and len(x) >= 3:
        emit(rt, 'LS01', ('FL' if m.src == 2 else 'OL', (x[1] >> 4) & 1, (x[1] >> 5) & 1,
                          (x[2] >> 0) & 1, (x[2] >> 3) & 1, (x[2] >> 4) & 3))
    continue
  if w == 'carState':
    cs = e.carState
    emit(rt, 'CS', ('cs', int(cs.standstill), int(cs.gasPressed), int(cs.brakePressed),
                    int(cs.cruiseState.enabled), round(cs.cruiseState.speed * 3.6, 1),
                    int(cs.accFaulted), int(getattr(cs, 'esp_hold_confirmation', 0))))
    v = round(cs.vEgo * 2) / 2.0
    emit(rt, 'v ', ('v', v))
  elif w == 'radarState':
    ld = e.radarState.leadOne
    emit(rt, 'RD', ('rd', int(ld.present), int(ld.radar), round(ld.dRel, 1), round(ld.vRel, 1),
                    round(ld.modelProb, 1)))
  elif w == 'carControl':
    emit(rt, 'CC', ('cc', round(e.carControl.actuators.accel, 1), int(e.carControl.longActive)))
  elif w == 'controlsState':
    emit(rt, 'CT', ('ct', str(e.controlsState.longControlState).split('.')[-1]))
  elif w == 'selfdriveState':
    ss = e.selfdriveState
    emit(rt, 'SS', ('ss', int(ss.enabled), str(ss.state).split('.')[-1][:10],
                    str(getattr(ss, 'alertText1', ''))[:28]))
