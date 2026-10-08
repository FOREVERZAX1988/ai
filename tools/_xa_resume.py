#!/usr/bin/env python3
"""_xa_resume.py <route> <segidx> —— 统计 OP 代发 RESUME 脉冲（LS_01 上升沿，src != 2）与蠕行区间。"""
import glob
import os
import sys

sys.path.insert(0, '/data/openpilot')
from openpilot.tools.lib.logreader import LogReader

route, segidx = sys.argv[1], int(sys.argv[2])
paths = sorted(glob.glob('/data/media/0/realdata/%s--*/rlog.zst' % route),
               key=lambda p: int(os.path.basename(os.path.dirname(p)).split('--')[-1]))
p = paths[segidx]

t0 = None
prev_op = {}
prev_ft = {}
pulses = []
ft_pulses = []
v = 0.0
creeps = []
creep_on = None
st_f = 0
for e in LogReader(p):
  t = e.logMonoTime / 1e9
  if t0 is None:
    t0 = t
  w = e.which()
  if w == 'can':
    for m in e.can:
      x = bytes(m.dat)
      if m.address == 267 and len(x) >= 3:
        rr = (x[2] >> 3) & 1
        if m.src == 2:
          if prev_ft.get('fr') == 0 and rr == 1:
            ft_pulses.append(t - t0)
          prev_ft['fr'] = rr
        else:
          if prev_op.get('fr') == 0 and rr == 1:
            pulses.append(t - t0)
          prev_op['fr'] = rr
      elif m.address == 269 and m.src == 2:
        st_f = (int.from_bytes(x, 'little') >> 57) & 7
  elif w == 'carState':
    v = e.carState.vEgo
    if v > 0.3 and creep_on is None:
      creep_on = t - t0
    elif v <= 0.3 and creep_on is not None:
      creeps.append((creep_on, t - t0))
      creep_on = None

print('OP RESUME 脉冲 (src!=2):', [round(x, 2) for x in pulses])
print('原厂 LS_01 RESUME 脉冲 (src=2):', [round(x, 2) for x in ft_pulses])
print('蠕行区间 (v>0.3):', [(round(a, 1), round(b, 1)) for a, b in creeps])
