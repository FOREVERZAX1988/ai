#!/usr/bin/env python3
"""_x2_timeline.py <route> <segidx> <lo> <hi>  —— 只打印变化帧的紧凑时间线。"""
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
shown = 0
for e in LogReader(p):
  t = e.logMonoTime / 1e9
  if t0 is None:
    t0 = t
  rt = t - t0
  if rt < lo or rt > hi:
    continue
  w = e.which()
  row = None
  if w == 'can':
    for m in e.can:
      x = bytes(m.dat)
      if m.address == 780:
        k = 'F2' if m.src == 2 else 'O2'
        row = (k, ((x[3] | (x[4] << 8)) & 0x3FF, (x[5] >> 6) & 3, g(x, 44, 2), g(x, 22, 2),
                   g(x, 12, 10) * 0.32))
      elif m.address == 269:
        k = 'F5' if m.src == 2 else 'O5'
        row = (k, (g(x, 57, 3), round(g(x, 32, 11) * 0.005 - 7.22, 2), g(x, 16, 10),
                   g(x, 62, 1), g(x, 43, 1), g(x, 61, 1)))
      if row:
        if prev.get(row[0]) != row[1]:
          prev[row[0]] = row[1]
          print(f"{rt:7.2f} {row[0]:3s} {row[1]}", flush=True)
          shown += 1
    continue
  if w == 'carState':
    cs = e.carState
    val = (round(cs.vEgo, 2), int(cs.standstill), int(cs.gasPressed), int(cs.brakePressed),
           int(cs.cruiseState.enabled), round(cs.cruiseState.speed * 3.6, 1), int(cs.accFaulted))
    key = 'CS'
  elif w == 'radarState':
    ld = e.radarState.leadOne
    val = (int(ld.present), int(ld.radar), round(ld.dRel, 1), round(ld.vRel, 2),
           round(ld.vLead, 2), round(ld.modelProb, 2))
    key = 'RD'
  elif w == 'carControl':
    val = (round(e.carControl.actuators.accel, 2), int(e.carControl.longActive))
    key = 'CC'
  elif w == 'controlsState':
    val = (str(e.controlsState.longControlState).split('.')[-1],)
    key = 'CT'
  elif w == 'selfdriveState':
    val = (int(e.selfdriveState.enabled), str(e.selfdriveState.state).split('.')[-1][:10])
    key = 'SS'
  else:
    continue
  if prev.get(key) != val:
    prev[key] = val
    print(f"{rt:7.2f} {key:3s} {val}", flush=True)
    shown += 1
print('rows', shown)
