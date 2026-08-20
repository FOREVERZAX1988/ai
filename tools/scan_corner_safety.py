#!/usr/bin/env python3
"""弯道系数安全验证：4f 弯道回放计算
①横向加速度 a_y=v²·curv（过弯物理需求 vs 轮胎极限~8-9m/s²，舒适余量取4-5）
②应用弯道系数后的新 max_accel（正数=不减速不骤停）
③被压帧（原 accel > 新上限）占比（效果证明）
④代表弯道时间线"""
import glob, sys, math
import numpy as np
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

SR, L = 15.0, 2.81
LIMIT = 1.2          # MacanAccelLimit 当前值
CORNER_MIN = 0.3     # 弯道系数下限

segs = sorted(glob.glob("/data/media/0/realdata/0000004f--*/rlog.zst"))[:6]

new_lims = []        # 弯道帧应用后上限
ays = []             # 弯道帧横向加速度
pressed = 0          # 原accel > 新上限（会被压住的帧）
curb_n = 0
events = []          # 代表事件（accel>1.0 且 |angle|>8°）
last_accel = 0.0
last_v = 0.0; last_angle = 0.0; last_en = False

for seg in segs:
  lr = LogReader(seg)
  for msg in lr:
    w = msg.which()
    if w == "carState":
      cs = msg.carState
      last_v, last_angle, last_en = cs.vEgo, cs.steeringAngleDeg, cs.cruiseState.enabled
    elif w == "carControl":
      accel = msg.carControl.actuators.accel
      if last_en and last_v > 1.0:
        ang = abs(last_angle)
        curv = math.radians(ang) / (SR * L)
        ay = last_v * last_v * curv
        factor = float(np.clip(1.0 - (ang - 5.0) / 25.0, CORNER_MIN, 1.0)) if ang > 5.0 else 1.0
        new_lim = min(LIMIT, LIMIT * factor) if ang > 5.0 else LIMIT
        if ang > 8.0:  # 弯道帧
          curb_n += 1
          new_lims.append(new_lim)
          ays.append(ay)
          if accel > new_lim:
            pressed += 1
          if accel > 1.0:
            events.append((last_angle, last_v * 3.6, accel, new_lim, ay))
    else:
      continue
  del lr

new_lims.sort(); ays.sort()
print(f"=== 4f 前6段 弯道帧（|angle|>8°）: {curb_n} ===")
print(f"\n① 横向加速度 a_y 分布（过弯物理需求）:")
print(f"   P50={ays[len(ays)//2]:.2f}  P95={ays[int(len(ays)*0.95)]:.2f}  P99={ays[int(len(ays)*0.99)]:.2f}  MAX={ays[-1]:.2f} m/s²")
print(f"   轮胎极限≈8-9 m/s²（干地），舒适余量 4-5 → 余量: {'充足 ✓' if ays[-1] < 4.0 else '需关注'}")
print(f"\n② 弯道系数应用后 纵向上限分布（min(1.2, 1.2×factor)）:")
print(f"   MIN={new_lims[0]:.2f}  P25={new_lims[len(new_lims)//4]:.2f}  中位={new_lims[len(new_lims)//2]:.2f}  MAX={new_lims[-1]:.2f} m/s²")
print(f"   全部为正（≥{min(new_lims):.2f}）→ 弯中只会减少加速、不会减速停车 ✓")
print(f"\n③ 被压帧（原accel>新上限，即\"原本会冲、现在被压住\"）: {pressed}/{curb_n} ({100*pressed/max(curb_n,1):.0f}%)")
print(f"\n④ 代表弯道事件（accel>1.0 且弯中）——新上限是多少:")
print(f"   {'angle°':>6} {'vkmh':>5} {'原accel':>7} {'新上限':>6} {'a_y':>5} | 判定")
for ang, v, accel, new_lim, ay in events[:10]:
  tag = "压住(不冲)" if accel > new_lim else "本就平顺"
  print(f"   {ang:>6.1f} {v:>5.0f} {accel:>7.2f} {new_lim:>6.2f} {ay:>5.2f} | {tag}")
