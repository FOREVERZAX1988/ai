#!/usr/bin/env python3
"""0002-0005 高速弯样本分析——验证 turnSpeed 在高速场景的价值
①各段高速占比（v>70km/h）②高速弯样本（v>70 且 a_y_est>0.8）
③原厂在高速弯的行为（前2s→后2s 车速变化=入弯减速？）④turn_speed(2.5) vs v"""
import glob, sys, math
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

SR, L = 15.0, 2.81
PREFIXES = ["00000002"]
MAX_SEG = 8

print("=== 各段概况 ===")
all_curves = []  # (prefix, seg, f, v_kph, angle, a_y, ts_kph, v_prev2s, v_next2s)
for pre in PREFIXES:
  segs = sorted(glob.glob(f"/data/media/0/realdata/{pre}--*/rlog.zst"))
  if not segs:
    segs = sorted(glob.glob(f"/data/media/0/realdata/{pre}--*--rlog.zst"))  # 旧版单文件格式
  print(f"\n{pre}: {len(segs)} 段")
  for si, seg in enumerate(segs[:MAX_SEG]):
    lr = LogReader(seg)
    f = 0; v = 0.0; angle = 0.0; en = False
    n_high = 0; n_total = 0
    for msg in lr:
      f += 1
      if msg.which() == "carState":
        cs = msg.carState
        v = cs.vEgo; angle = cs.steeringAngleDeg; en = cs.cruiseState.enabled
      if en and v > 1.0:
        n_total += 1
        if v > 70/3.6: n_high += 1
    del lr
    if n_total > 0:
      print(f"  段{si}: 帧数~{f} 高速占比 {100*n_high/max(n_total,1):.0f}% (v>70km/h)")
    else:
      print(f"  段{si}: 无激活帧")

# 高速弯样本收集（两遍：先收集候选，再查前后车速）
print("\n=== 高速弯样本（v>70km/h 且 a_y_est>0.8）===")
cands = []
for pre in PREFIXES:
  segs = sorted(glob.glob(f"/data/media/0/realdata/{pre}--*/rlog.zst"))
  if not segs:
    segs = sorted(glob.glob(f"/data/media/0/realdata/{pre}--*--rlog.zst"))  # 旧版单文件格式
  for si, seg in enumerate(segs[:MAX_SEG]):
    lr = LogReader(seg)
    f = 0; v = 0.0; angle = 0.0; en = False
    for msg in lr:
      f += 1
      if msg.which() == "carState":
        cs = msg.carState
        v = cs.vEgo; angle = cs.steeringAngleDeg; en = cs.cruiseState.enabled
        if en and v > 70/3.6:
          curv = math.radians(abs(angle)) / (SR * L)
          ay = v * v * curv
          if ay > 0.8:
            ts = math.sqrt(2.5 / curv) * 3.6 if curv > 1e-6 else 999
            cands.append((pre, si, f, v*3.6, angle, ay, ts))
    del lr

print(f"高速弯候选帧: {len(cands)}")
if cands:
  over = [c for c in cands if c[3] > c[6]]
  print(f"其中 v > turn_speed(2.5): {len(over)}/{len(cands)}（这些是'超舒适限速'行驶——turnSpeed 有价值）")
  # 代表帧
  print("\n代表帧（段/帧/vkmh/angle°/a_y/turn_speed）：")
  for c in sorted(cands, key=lambda x: -x[5])[:8]:
    print(f"  {c[0]} 段{c[1]} 帧{c[2]:>6} v={c[3]:>4.0f} angle={c[4]:>5.1f}° a_y={c[5]:.2f} ts={c[6]:>4.0f}")
