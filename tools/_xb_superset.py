#!/usr/bin/env python3
"""_xb_superset.py <route> <segidx> —— ACC_02 原厂(bus2/src2) vs OP 代发(bus0/128) 的"前车信息"覆盖对比：
逐 40ms 时间格取每源最新值，统计 idx>0 / rel==1 的格数，以及"原厂有而 OP 无"的时间格（应恒为 0）。"""
import glob
import os
import sys

sys.path.insert(0, '/data/openpilot')
from openpilot.tools.lib.logreader import LogReader

route, segidx = sys.argv[1], int(sys.argv[2])
paths = sorted(glob.glob('/data/media/0/realdata/%s--*/rlog.zst' % route),
               key=lambda p: int(os.path.basename(os.path.dirname(p)).split('--')[-1]))
p = paths[segidx]

cur_f = None   # (idx, rel)
cur_o = None
cells = {}
t0 = None
nf = no = 0
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
      nf += 1
    else:
      cur_o = val
      no += 1
    if cur_f is not None and cur_o is not None:
      cell = int((t - t0) * 25)
      cells[cell] = (cur_f, cur_o)

f_lead = o_lead = 0
f_only = o_only = both = 0
for cell, (f, o) in sorted(cells.items()):
  fl = f[0] > 0 or f[1] == 1
  ol = o[0] > 0 or o[1] == 1
  f_lead += fl
  o_lead += ol
  if fl and ol:
    both += 1
  elif fl:
    f_only += 1
  elif ol:
    o_only += 1
print(f"frames: factory={nf} op={no} (ratio {nf / max(no, 1):.2f})")
print(f"cells={len(cells)}  factory_lead={f_lead}  op_lead={o_lead}  both={both}  "
      f"factory_only={f_only}  op_only={o_only}")
