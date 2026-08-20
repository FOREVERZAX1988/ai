#!/usr/bin/env python3
"""转向角系数（steerRatio）拟合 v2 —— 用 ESP_Gierrate（ESP_02@257 40|14 scale0.01 + 符号位 54|1）
公式：曲率 = yawRate / vEgo；前轮角 δ = atan(wheelbase * curvature)
steerRatio = 方向盘角(rad) / δ(rad)
过滤：v>5m/s、|yaw|<25°/s（线性区）、|sw|<200°、|δ|>0.03°（去零噪）
输出：总体分布 + 速度分箱 + yaw分箱（动态转向比 PDS 检查）"""
import glob, sys, math
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

L = 2.81   # Macan 轴距 m
DEG = math.pi / 180.0
segs = sorted(glob.glob("/data/media/0/realdata/0000004f--*/rlog.zst"))
all_sr = []
for si, p in enumerate(segs):
    try:
        lr = LogReader(p)
    except Exception:
        continue
    st = {"v": 0.0, "sw": 0.0, "en": False, "yaw": 0.0}
    n = 0
    for msg in lr:
        if msg.which() == "carState":
            cs = msg.carState
            st["v"] = cs.vEgo
            st["sw"] = cs.steeringAngleDeg
            st["en"] = cs.cruiseState.enabled
        elif msg.which() == "can":
            for c in msg.can:
                if c.address == 257 and len(c.dat) >= 7:
                    d = bytes(c.dat)
                    raw = 0
                    for i in range(14):
                        byte = (40 + i) // 8
                        bit = (40 + i) % 8
                        if d[byte] & (1 << bit): raw |= (1 << i)
                    vz = (d[6] >> 6) & 1 if len(d) > 6 else 0  # 54|1 -> byte6 bit6
                    st["yaw"] = raw * 0.01 * (-1 if vz else 1) * DEG  # rad/s
        if st["en"] and st["v"] > 5.0 and abs(st["yaw"]) < 25 * DEG and abs(st["sw"]) < 200:
            if abs(st["yaw"]) < 0.0005:
                continue
            curv = st["yaw"] / st["v"]
            front = math.atan(L * curv)
            if abs(front) < 0.0005:
                continue
            sr = abs(st["sw"] * DEG / front)
            if 5 < sr < 40:
                all_sr.append((sr, st["v"] * 3.6, abs(st["yaw"]) * 180 / math.pi, abs(st["sw"])))
        n += 1
        if n > 200000: break
    del lr

print(f"有效样本: {len(all_sr)}")
if len(all_sr) < 100:
    print("样本不足")
    sys.exit(0)
import statistics
srs = [x[0] for x in all_sr]
print(f"\n=== 总体分布 ===")
print(f"mean={statistics.mean(srs):.2f}  median={statistics.median(srs):.2f}  std={statistics.stdev(srs):.2f}")
s = sorted(srs)
for q in (5, 25, 75, 95):
    print(f"  P{q}={s[int(len(s) * q / 100)]:.2f}")
print(f"\n=== 速度分箱（PDS 动态转向比检查）===")
for lo, hi in [(0, 40), (40, 60), (60, 80), (80, 100), (100, 120), (120, 200)]:
    sel = [x for x in all_sr if lo <= x[1] < hi]
    if len(sel) >= 20:
        vs = [x[0] for x in sel]
        print(f"  {lo:>3}-{hi:<3} km/h: n={len(sel):>5}  mean={statistics.mean(vs):.2f}  median={statistics.median(vs):.2f}")
print(f"\n=== 横摆角速度分箱（|yaw| 相关性）===")
for lo, hi in [(0, 5), (5, 10), (10, 15), (15, 25)]:
    sel = [x for x in all_sr if lo <= x[2] < hi]
    if len(sel) >= 20:
        vs = [x[0] for x in sel]
        print(f"  {lo:>2}-{hi:<2} °/s:  n={len(sel):>5}  mean={statistics.mean(vs):.2f}  median={statistics.median(vs):.2f}")
print(f"\n=== 方向盘角分箱 ===")
for lo, hi in [(0, 20), (20, 50), (50, 100), (100, 200)]:
    sel = [x for x in all_sr if lo <= x[3] < hi]
    if len(sel) >= 20:
        vs = [x[0] for x in sel]
        print(f"  {lo:>3}-{hi:<3} °:    n={len(sel):>5}  mean={statistics.mean(vs):.2f}  median={statistics.median(vs):.2f}")
