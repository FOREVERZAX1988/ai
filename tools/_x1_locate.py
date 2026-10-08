#!/usr/bin/env python3
"""临时：定位 route 91 中 bus2 idx 常量保持(188) 的段 + 该窗口关键量。"""
import glob
import os
import sys

sys.path.insert(0, '/data/openpilot')
from openpilot.tools.lib.logreader import LogReader

ROUTE = sys.argv[1] if len(sys.argv) > 1 else '00000091--98208e01cb'
LO = int(sys.argv[2]) if len(sys.argv) > 2 else 5
HI = int(sys.argv[3]) if len(sys.argv) > 3 else 14

paths = sorted(glob.glob('/data/media/0/realdata/%s--*/rlog.zst' % ROUTE),
               key=lambda p: int(os.path.basename(os.path.dirname(p)).split('--')[-1]))

# route 首帧时间
t0 = None
for p in paths[:1]:
  for e in LogReader(p):
    t0 = e.logMonoTime / 1e9
    break
print('route t0 =', t0)

for p in paths[LO:HI]:
  idx2 = None
  idx_hist = {}
  stand = 0
  n = 0
  tmin = tmax = None
  # idx 常量 run 统计
  run_i = None
  run_n = 0
  run_t = None
  runs = []
  f2_cnt = o2_cnt = 0
  for e in LogReader(p):
    t = e.logMonoTime / 1e9
    if tmin is None:
      tmin = t
    tmax = t
    w = e.which()
    if w == 'can':
      for m in e.can:
        x = bytes(m.dat)
        if m.address == 780:
          i = (x[3] | (x[4] << 8)) & 0x3FF
          if m.src == 2:
            f2_cnt += 1
            idx_hist[i] = idx_hist.get(i, 0) + 1
            if i != run_i:
              if run_i and run_n >= 15:
                runs.append((run_t, t, run_i, run_n))
              run_i, run_n, run_t = i, 1, t
            else:
              run_n += 1
          else:
            o2_cnt += 1
    elif w == 'carState':
      n += 1
      stand += int(e.carState.standstill)
  top = sorted(idx_hist.items(), key=lambda kv: -kv[1])[:5]
  print(f"seg{os.path.basename(os.path.dirname(p)).split('--')[-1]:>3s} "
        f"t {tmin - t0:7.1f}~{tmax - t0:7.1f} (abs {tmin:.1f}) CS={n} stand={stand} "
        f"F2={f2_cnt} O2={o2_cnt} top={top}")
  for r in sorted(runs, key=lambda r: -(r[1] - r[0]))[:4]:
    print(f"      idx={r[2]} const {r[1] - r[0]:5.1f}s  t {r[0] - t0:7.1f}~{r[1] - t0:7.1f} "
          f"(abs {r[0]:.1f}~{r[1]:.1f})")
