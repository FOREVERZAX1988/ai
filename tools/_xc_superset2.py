#!/usr/bin/env python3
"""_xc_superset2.py <route> <segidx> —— 同 _xb，但打印 "原厂有 / OP 无" 的具体时间点。"""
import glob
import os
import sys

sys.path.insert(0, '/data/openpilot')
from openpilot.tools.lib.logreader import LogReader

route, segidx = sys.argv[1], int(sys.argv[2])
paths = sorted(glob.glob('/data/media/0/realdata/%s--*/rlog.zst' % route),
               key=lambda p: int(os.path.basename(os.path.dirname(p)).split('--')[-1]))
p = paths[segidx]

cur_f = cur_o = None
cells = {}
t0 = None
for e in LogReader(p):
  t = e.logMonoTime / 1e9
  if t0 is None:
    t0 = t
  if e.which() != 'can':
    continue
  for m in e.can:
    x = bytes(m.dat)
    if m.address != 780:
      continue
    val = ((x[3] | (x[4] << 8)) & 0x3FF, (x[5] >> 6) & 3)
    if m.src == 2:
      cur_f = val
    else:
      cur_o = val
    if cur_f is not None and cur_o is not None:
      cells[int((t - t0) * 25)] = (cur_f, cur_o)

f_only = []
o_only = []
for cell, (f, o) in sorted(cells.items()):
  fl = f[0] > 0 or f[1] == 1
  ol = o[0] > 0 or o[1] == 1
  if fl and not ol:
    f_only.append((cell / 25.0, f[0]))
  elif ol and not fl:
    o_only.append((cell / 25.0, o[0]))
print('factory_only cells:', [(round(a, 1), b) for a, b in f_only])
print('op_only cells:', [(round(a, 1), b) for a, b in o_only[:40]])
