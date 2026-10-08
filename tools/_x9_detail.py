#!/usr/bin/env python3
"""_x9_detail.py <route> <seg> <lo> <hi> —— 0.25s 采样：v / 原厂 idx / 视觉距离 / 原厂 st,anh / OP engaged。
用途：静止或蠕行时原厂 Abstandsindex 是否仍在更新（判定"冻结"假设）。"""
import glob
import os
import sys

sys.path.insert(0, '/data/openpilot')
from openpilot.tools.lib.logreader import LogReader

route, segidx, lo, hi = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
paths = sorted(glob.glob('/data/media/0/realdata/%s--*/rlog.zst' % route),
               key=lambda p: int(os.path.basename(os.path.dirname(p)).split('--')[-1]))
p = paths[segidx]

cur = {'idx': 0, 'vis': 0.0, 'st': 0, 'anh': 0, 'en': 0}
rows = []
t0 = None
for e in LogReader(p):
  t = e.logMonoTime / 1e9
  if t0 is None:
    t0 = t
  w = e.which()
  if w == 'can':
    for m in e.can:
      x = bytes(m.dat)
      i = int.from_bytes(x, 'little')
      if m.address == 780 and m.src == 2:
        cur['idx'] = (x[3] | (x[4] << 8)) & 0x3FF
      elif m.address == 269 and m.src == 2:
        cur['st'] = (i >> 57) & 7
        cur['anh'] = (i >> 62) & 1
    continue
  if w == 'carState':
    rows.append((t - t0, e.carState.vEgo, cur['idx'], cur['vis'], cur['st'], cur['anh'], cur['en'],
                 int(e.carState.cruiseState.enabled)))
  elif w == 'modelV2':
    try:
      lds = e.modelV2.leadsV3
      cur['vis'] = float(lds[0].x[0]) if len(lds) and lds[0].prob > 0.5 else 0.0
    except Exception:
      pass
  elif w == 'selfdriveState':
    cur['en'] = int(e.selfdriveState.enabled)

print('  t      v    idx   vis   st anh ss cruise')
last = None
for r in rows:
  if r[0] < lo or r[0] > hi:
    continue
  b = int(r[0] * 4)
  if b == last:
    continue
  last = b
  print(f"{r[0]:7.2f} {r[1]:5.2f} {r[2]:5d} {r[3]:5.1f} {r[4]:3d} {r[5]:3d} {r[6]:3d} {r[7]:3d}")
