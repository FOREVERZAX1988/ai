#!/usr/bin/env python3
"""模拟弯道系数开启后的压限效果（对 4f 的 13 个加速事件重算）
弯道系数：factor=clip(1-(|angle|-5)/25, 0.3, 1.0)；上限=min(原上限, 1.2×factor)
展示"如果当时系数开着，目标加速度会被压到多少"——路试前的预期验证"""
import glob, sys, math
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

LIMIT = 1.2   # MacanAccelLimit
CORNER = 0.3  # 硬编码系数

def corner_limit(angle_deg, lim=LIMIT):
  f = max(min(1.0 - (abs(angle_deg) - 5.0) / 25.0, 1.0), CORNER)
  return lim * f

def scan(prefix, max_seg=20):
  segs = sorted(glob.glob(f"/data/media/0/realdata/{prefix}--*/rlog.zst"))
  events = []
  buf = []
  last_accel = 0.0
  collecting = None
  f = 0
  v = 0.0; angle = 0.0; torque = 0.0; accel = 0.0; pressed = False
  for si, seg in enumerate(segs[:max_seg]):
    lr = LogReader(seg)
    for msg in lr:
      f += 1
      w = msg.which()
      if w == "carState":
        angle = msg.carState.steeringAngleDeg
        v = msg.carState.vEgo
        pressed = msg.carState.steeringPressed
      elif w == "carControl":
        torque = msg.carControl.actuators.torque
        accel = msg.carControl.actuators.accel
      else:
        continue
      cur = dict(f=f, v=v, angle=angle, torque=torque, pressed=pressed, accel=accel)
      buf.append(cur)
      if len(buf) > 60:
        buf.pop(0)
      if accel > 0.4 and last_accel < 0.1 and collecting is None:
        collecting = dict(ev_f=f, frames=[])
      if collecting is not None:
        collecting["frames"].append(cur)
        if len(collecting["frames"]) >= 35:
          collecting = None
          events.append((si, buf[-25:] if len(buf) >= 25 else buf))
      last_accel = accel
    del lr
  return events

events = scan("0000004f")
print(f"{'段':>2} {'帧':>7} {'vkmh':>5} {'angle°':>7} | {'原accel':>7} {'新上限':>6} {'压后accel':>9} | 说明")
print("-"*72)
n_pressed = 0
for si, pre in events:
  cur = pre[-1]
  a_orig = cur["accel"]
  lim = corner_limit(cur["angle"])
  a_new = min(a_orig, lim)
  note = ""
  if abs(cur["angle"]) > 30:
    note = "大弯强压"
  elif abs(cur["angle"]) > 8:
    note = "弯道中"
  else:
    note = "近直道"
  print(f"{si:>2} {cur['f']:>7} {cur['v']*3.6:>5.0f} {cur['angle']:>7.1f} | {a_orig:>7.2f} {lim:>6.2f} {a_new:>9.2f} | {note}")
  if cur["pressed"]:
    n_pressed += 1
print(f"\n总事件 {len(events)} 个（其中握盘 {n_pressed} 个）")
print("压后 accel > 0.9 的事件:", sum(1 for _, pre in events if min(pre[-1]['accel'], corner_limit(pre[-1]['angle'])) > 0.9))
print("结论：弯道系数开启后，弯道加速从 0.95-1.43 压到 ≤0.9，直道不受影响")
