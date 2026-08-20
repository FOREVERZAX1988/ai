#!/usr/bin/env python3
"""turnSpeed（转弯目标速度）机制回放验证——基于现有 routes
turn_speed = sqrt(A_Y_MAX / curvature_est)，curvature_est = rad(angle)/(SR*L)
统计：①弯道帧(|angle|>8°)中 v_ego > turn_speed 的占比（限速必要性）
      ②实际横向加速度分布（校准 A_Y_MAX）③加速事件的预期压限"""
import glob, sys, math
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

SR, L = 15.0, 2.81  # 动态转向比低速段（<140km/h）
segs = sorted(glob.glob("/data/media/0/realdata/0000004f--*/rlog.zst"))

stats = {ay: {"n": 0, "over": 0} for ay in [2.0, 2.5, 3.0]}
ay_all = []
events = []  # 加速事件 (v, angle, accel)
buf = []
last_accel = 0.0

for si in range(15):
  lr = LogReader(segs[si])
  f = 0
  v = 0.0; angle = 0.0; accel = 0.0; en = False
  for msg in lr:
    f += 1
    if msg.which() == "carState":
      cs = msg.carState
      v = cs.vEgo
      angle = cs.steeringAngleDeg
      en = cs.cruiseState.enabled
    elif msg.which() == "carControl":
      accel = msg.carControl.actuators.accel
    else:
      continue
    if en and v > 1.0:
      curv = math.radians(abs(angle)) / (SR * L)
      if curv > 1e-6:
        ay = v * v * curv
        ay_all.append(ay)
        for aymax in stats:
          ts = math.sqrt(aymax / curv)
          if abs(angle) > 8.0:  # 弯道帧
            stats[aymax]["n"] += 1
            if v > ts:
              stats[aymax]["over"] += 1
    # 加速事件检测（复用 scan_accel_lat 逻辑）
    if accel > 0.4 and last_accel < 0.1:
      events.append((v, angle, accel))
    last_accel = accel
  del lr

print("=== 弯道帧超速占比（限速必要性）===")
for aymax, s in stats.items():
  pct = 100 * s["over"] / max(s["n"], 1)
  print(f"  A_Y_MAX={aymax} m/s²: 弯道帧 {s['n']} 中超速 {s['over']} ({pct:.0f}%)")

ay_all.sort()
n = len(ay_all)
print(f"\n=== 实际横向加速度分布（{n} 帧，校准 A_Y_MAX）===")
for p in [50, 85, 90, 95, 99]:
  print(f"  P{p}: {ay_all[int(n*p/100)]:.2f} m/s²")

print(f"\n=== 加速事件 turnSpeed 预期（A_Y_MAX=2.5）===")
print(f"{'vkmh':>5} {'angle°':>6} {'accel':>5} | {'turn_speed':>9} {'v<ts?':>5} | 判断")
n_curb = 0
for v, angle, accel in events:
  curv = math.radians(abs(angle)) / (SR * L)
  ts = math.sqrt(2.5 / curv) if curv > 1e-6 else 999
  ts_kph = ts * 3.6
  v_kph = v * 3.6
  under = v < ts
  if not under: n_curb += 1
  tag = "限速低于当前车速→入弯前该减速" if not under else ("弯道中接近限速" if abs(angle) > 8 else "直道不限")
  print(f"{v_kph:>5.0f} {angle:>6.1f} {accel:>5.2f} | {ts_kph:>9.0f} {str(under):>5} | {tag}")
print(f"\n加速事件中 v > turn_speed 的事件: {n_curb}/{len(events)}（这些是入弯/弯道中已超限速的）")
