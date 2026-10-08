#!/usr/bin/env python3
"""_x8_locate_sng.py <route> <sec_lo> <sec_hi> —— 每个 seg 一行紧凑摘要（原厂 ACC routes 定位 SnG）。"""
import glob
import os
import sys

sys.path.insert(0, '/data/openpilot')
from openpilot.tools.lib.logreader import LogReader

route, slo, shi = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
paths = sorted(glob.glob('/data/media/0/realdata/%s--*/rlog.zst' % route),
               key=lambda p: int(os.path.basename(os.path.dirname(p)).split('--')[-1]))

for si in range(slo, min(shi, len(paths))):
  p = paths[si]
  rows = []
  cur = {'idx': 0, 'vis': 0.0}
  for e in LogReader(p):
    w = e.which()
    if w == 'can':
      for m in e.can:
        if m.address == 780 and m.src == 2:
          x = bytes(m.dat)
          cur['idx'] = (x[3] | (x[4] << 8)) & 0x3FF
    elif w == 'carState':
      rows.append((e.logMonoTime / 1e9, e.carState.vEgo, cur['idx'], cur['vis']))
    elif w == 'modelV2':
      try:
        lds = e.modelV2.leadsV3
        if len(lds) and lds[0].prob > 0.5:
          cur['vis'] = float(lds[0].x[0])
      except Exception:
        pass
  if len(rows) < 10:
    print(f"seg{si} rows={len(rows)}")
    continue
  t0 = rows[0][0]
  dur = rows[-1][0] - t0
  slow = [r for r in rows if r[1] < 0.3]
  best = (0, None, None)
  s = None
  for r in rows:
    if r[1] < 0.15:
      s = r[0] if s is None else s
    elif s is not None:
      if r[0] - s > best[0]:
        best = (r[0] - s, s, r[0])
      s = None
  if s is not None and rows[-1][0] - s > best[0]:
    best = (rows[-1][0] - s, s, rows[-1][0])
  dur_st, a, b = best
  seg_stand = [r for r in rows if a is not None and a <= r[0] <= b]
  idxs = sorted({r[2] for r in seg_stand})
  vis = [r[3] for r in seg_stand if r[3] > 0]
  where = 'n/a' if a is None else f"{a - t0:5.0f}"
  print(f"seg{si:>3d} dur={dur:5.0f}s slow<0.3={len(slow) / len(rows) * 100:4.0f}% "
        f"longest_stand={dur_st:5.1f}s@{where} uniq_idx_in_stand={len(idxs)} "
        f"idx={idxs[:8]} vis_med={0 if not vis else sorted(vis)[len(vis) // 2]:5.1f} "
        f"idx_uniq_whole={len({r[2] for r in rows})}")
