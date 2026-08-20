#!/usr/bin/env python3
"""高速段弯道分析（0002段32-38/58-62 + 0004段19-26）
①高速弯帧（v>70km/h 且 a_y_est>0.8）数量与代表帧
②v > turn_speed(2.5) 的占比（超舒适限速行驶）
③高速弯横向加速度分布（校准 A_Y_MAX）"""
import glob, sys, math
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

SR, L = 15.0, 2.81
TARGETS = [
  ("00000002", [32,33,34,35,36,37,38,58,59,60,61,62]),
  ("00000004", [19,20,21,22,23,24,25,26]),
]

cands = []
ay_all = []
n_high_total = 0
for pre, segs in TARGETS:
  for si in segs:
    files = sorted(glob.glob(f"/data/media/0/realdata/{pre}--*--{si}--rlog.zst"))
    if not files:
      files = sorted(glob.glob(f"/data/media/0/realdata/{pre}--*/{si}/rlog.zst"))
    if not files:
      print(f"{pre} 段{si}: 找不到 rlog")
      continue
    lr = LogReader(files[0])
    f = 0
    for msg in lr:
      f += 1
      if msg.which() == "carState":
        cs = msg.carState
        v = cs.vEgo
        if v > 70/3.6:
          n_high_total += 1
          angle = cs.steeringAngleDeg
          curv = math.radians(abs(angle)) / (SR * L)
          ay = v * v * curv
          ay_all.append(ay)
          if ay > 0.8:
            ts = math.sqrt(2.5 / curv) * 3.6 if curv > 1e-6 else 999
            cands.append((pre, si, f, v*3.6, angle, ay, ts))
    del lr

print(f"高速帧(v>70km/h): {n_high_total}")
print(f"高速弯帧(a_y>0.8): {len(cands)}")

if cands:
  over = [c for c in cands if c[3] > c[6]]
  print(f"其中 v > turn_speed(2.5): {len(over)}/{len(cands)}（超舒适限速行驶——turnSpeed 有价值）")
  print("\n代表帧（route/段/帧/vkmh/angle°/a_y/turn_speed）：")
  for c in sorted(cands, key=lambda x: -x[5])[:12]:
    tag = "  ←超限速" if c[3] > c[6] else ""
    print(f"  {c[0]} 段{c[1]} 帧{c[2]:>6} v={c[3]:>4.0f} angle={c[4]:>5.1f}° a_y={c[5]:.2f} ts={c[6]:>4.0f}{tag}")
else:
  print("（高速段上没有 a_y>0.8 的弯——路况太直或弯太缓）")

ay_all.sort()
n = len(ay_all)
print(f"\n高速帧横向加速度分布（{n} 帧）：")
for p in [50, 85, 90, 95, 99]:
  print(f"  P{p}: {ay_all[int(n*p/100)]:.2f} m/s²")
