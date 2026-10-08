#!/usr/bin/env python3
"""_x7_sngscan.py <route> <segidx> [pre] [post] —— 打印该 seg 内最长静止段的窗口逐 0.5s 采样：
t, vEgo, 原厂 idx(bus2), 视觉 lead 距离(modelV2 leadsV3[0].x), 融合 dRel(radarState),
原厂 ACC_05 st/anh, OP 的 LS_01 RESUME 位。
用途：① 原厂 idx 在静止/蠕行时是否还更新；② 低速 idx vs 真实视觉距离标定。
"""
import glob
import os
import sys

sys.path.insert(0, '/data/openpilot')
from openpilot.tools.lib.logreader import LogReader

route, segidx = sys.argv[1], int(sys.argv[2])
pre = float(sys.argv[3]) if len(sys.argv) > 3 else 25.0
post = float(sys.argv[4]) if len(sys.argv) > 4 else 15.0

paths = sorted(glob.glob('/data/media/0/realdata/%s--*/rlog.zst' % route),
               key=lambda p: int(os.path.basename(os.path.dirname(p)).split('--')[-1]))
p = paths[segidx]

rows = []          # (t, v, idx, visd, fused, st, anh, resume_op, resume_ft)
cur = {'v': 0.0, 'idx': 0, 'vis': 0.0, 'fused': 0.0, 'st': 0, 'anh': 0, 'rO': 0, 'rF': 0}
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
      elif m.address == 269:
        if m.src == 2:
          cur['st'] = (i >> 57) & 7
          cur['anh'] = (i >> 62) & 1
        if len(x) >= 3 and m.address == 267:
          if m.src == 2:
            cur['rF'] = (x[2] >> 3) & 1
          else:
            cur['rO'] = (x[2] >> 3) & 1
    continue
  if w == 'carState':
    cur['v'] = e.carState.vEgo
  elif w == 'radarState':
    cur['fused'] = e.radarState.leadOne.dRel if e.radarState.leadOne.present else 0.0
  elif w == 'modelV2':
    try:
      lds = e.modelV2.leadsV3
      cur['vis'] = float(lds[0].x[0]) if len(lds) and lds[0].prob > 0.5 else 0.0
    except Exception:
      pass
  rows.append((t - t0, cur['v'], cur['idx'], cur['vis'], cur['fused'], cur['st'], cur['anh'],
               cur['rO'], cur['rF']))

# 找最长静止段
best = (0, None, None)
run_s = None
for r in rows:
  if r[1] < 0.15:
    if run_s is None:
      run_s = r[0]
  else:
    if run_s is not None and r[0] - run_s > best[0]:
      best = (r[0] - run_s, run_s, r[0])
    run_s = None
if run_s is not None and rows[-1][0] - run_s > best[0]:
  best = (rows[-1][0] - run_s, run_s, rows[-1][0])
dur, a, b = best
print(f"seg{segidx} 最长静止 {dur:.1f}s @ {a:.1f}~{b:.1f}s (seg 内相对)")
lo, hi = max(0.0, (a or 0) - pre), (b or 0) + post
sampled = []
last_bucket = None
for r in rows:
  if r[0] < lo or r[0] > hi:
    continue
  bucket = int(r[0] * 2)
  if bucket != last_bucket:
    sampled.append(r)
    last_bucket = bucket
    if len(sampled) > 130:
      break
print('   t     v    idx  vis   fused  st anh rO rF')
for r in sampled:
  print(f"{r[0]:7.2f} {r[1]:5.2f} {r[2]:5d} {r[3]:5.1f} {r[4]:5.1f} {r[5]:3d} {r[6]:3d} {r[7]:2d} {r[8]:2d}")
# idx 在该窗口的统计
win = [r for r in rows if lo <= r[0] <= hi]
stand = [r for r in win if r[1] < 0.15]
if stand:
  idxs = [r[2] for r in stand]
  print(f"静止帧 {len(stand)} idx 唯一值 {sorted(set(idxs))[:12]} (min {min(idxs)}, max {max(idxs)})")
  vis = [r[3] for r in stand if r[3] > 0]
  if vis:
    print(f"静止帧视觉距离 min/med/max = {min(vis):.1f}/{sorted(vis)[len(vis) // 2]:.1f}/{max(vis):.1f}")
