#!/usr/bin/env python3
"""弯道加速事件横向状态分析（4f/4d）——验证"方向盘释放导致加速"假设
对每个"突然加速"事件（目标加速度: <0.1 → >0.4 突变），检查加速瞬间：
  1. 方向盘角 |angle| 是否还大（>8°=没回正就加速）
  2. 期望转向力矩 torque 是否突然掉 0（=横向释放/系统松手）
  3. 驾驶员是否握盘（steeringPressed）
若"angle还大 + torque掉0"为主 → 根因是横向释放（不是弯道限制解除）"""
import glob, sys
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

def scan(prefix, max_seg=20):
  segs = sorted(glob.glob(f"/data/media/0/realdata/{prefix}--*/rlog.zst"))
  events = []
  buf = []
  last_accel = 0.0
  collecting = None
  f = 0
  v = 0.0; angle = 0.0; torque = 0.0; accel = 0.0; pressed = False; en = False
  for si, seg in enumerate(segs[:max_seg]):
    lr = LogReader(seg)
    for msg in lr:
      f += 1
      w = msg.which()
      if w == "carState":
        angle = msg.carState.steeringAngleDeg
        v = msg.carState.vEgo
        pressed = msg.carState.steeringPressed
        en = msg.carState.cruiseState.enabled
      elif w == "carControl":
        torque = msg.carControl.actuators.torque
        accel = msg.carControl.actuators.accel
      else:
        continue
      cur = dict(f=f, v=v, angle=angle, torque=torque, pressed=pressed, accel=accel, en=en)
      buf.append(cur)
      if len(buf) > 60:
        buf.pop(0)
      # 突变加速检测
      if accel > 0.4 and last_accel < 0.1 and collecting is None:
        collecting = dict(ev_f=f, frames=[])
      if collecting is not None:
        collecting["frames"].append(cur)
        if len(collecting["frames"]) >= 35:
          ev = collecting
          collecting = None
          events.append((si, ev["ev_f"], buf[-25:] if len(buf) >= 25 else buf, ev["frames"]))
      last_accel = accel
    del lr

  n_ev = len(events)
  n_angle_big = 0   # 加速时 |angle|>8°
  n_torque_drop = 0 # 加速前 torque 掉 0（横向释放）
  n_torque_big = 0  # 加速时 torque 还大（系统在转）
  detail = []
  for si, ev_f, pre, post in events:
    cur = post[0]
    torque_prev = [p["torque"] for p in pre[-5:]] if pre else []
    torque_max_before = max(abs(x) for x in torque_prev) if torque_prev else 0
    angle_big = abs(cur["angle"]) > 8.0
    torque_drop = torque_max_before > 0.25 and abs(cur["torque"]) < 0.08
    torque_still = abs(cur["torque"]) > 0.25
    if angle_big: n_angle_big += 1
    if torque_drop: n_torque_drop += 1
    if torque_still: n_torque_big += 1
    if len(detail) < 6:
      detail.append((si, ev_f, cur["v"]*3.6, cur["angle"], torque_max_before, cur["torque"], cur["pressed"], cur["accel"]))
  return n_ev, n_angle_big, n_torque_drop, n_torque_big, detail

for prefix in ["0000004f", "0000004d"]:
  n_ev, n_ab, n_sd, n_sb, det = scan(prefix)
  print(f"\n{'='*60}\n{prefix}：加速事件 {n_ev} 个")
  print(f"  加速时 |angle|>8°（方向盘没回正就加速）: {n_ab} ({100*n_ab/max(n_ev,1):.0f}%)")
  print(f"  加速前期望力矩掉0（横向释放/松手）: {n_sd} ({100*n_sd/max(n_ev,1):.0f}%)")
  print(f"  加速时期望力矩还大（系统仍在转）: {n_sb} ({100*n_sb/max(n_ev,1):.0f}%)")
  print("  代表事件（段/帧/vkmh/angle°/力矩前max/力矩现在/握盘/目标加速度）:")
  for d in det:
    print(f"    段{d[0]} 帧{d[1]:>6} v={d[2]:>4.0f} angle={d[3]:>6.1f}° 力矩前={d[4]:.2f} 力矩现={d[5]:.2f} 握盘={d[6]} accel={d[7]:.2f}")
