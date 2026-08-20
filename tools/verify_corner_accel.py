#!/usr/bin/env python3
"""弯道横纵向协调统计验证（v2：全段统计，不依赖事件检测）
对比两种 a_y 估算：
  a_y_steers = v²·angle(rad)/(SR·L)  —— 当前代码
  a_y_curv   = v²·lateralPlan.curvature —— 模型曲率（官方新版）
统计：激活帧中，"方向盘已回正(|ay_s|<0.2) 但模型曲率仍大(|ay_c|>0.5)" 的帧占比
= 当前代码已解除加速限制、但车头实际还在弯里的时间占比（即'头没转正就加速'的窗口）"""
import glob, sys, math
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

SR, L = 16.2, 2.81
segs = sorted(glob.glob("/data/media/0/realdata/0000004f--*/rlog.zst"))

tot = {"n": 0, "in_curv": 0, "curv_but_straight_angle": 0}
samples = []
for si in range(15):
    lr = LogReader(segs[si])
    st = {"f": 0, "v": 0.0, "angle": 0.0, "curv": 0.0, "en": False}
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            st["v"] = msg.carState.vEgo
            st["angle"] = msg.carState.steeringAngleDeg
            st["en"] = msg.carState.cruiseState.enabled
        elif msg.which() == "carOutput":
            st["curv"] = msg.carOutput.curvature
        if st["en"] and st["v"] > 3.0:
            v = st["v"]
            ay_s = v**2 * math.radians(abs(st["angle"])) / (SR * L)
            ay_c = v**2 * abs(st["curv"])
            tot["n"] += 1
            if ay_c > 0.5:
                tot["in_curv"] += 1
                if ay_s < 0.2:
                    tot["curv_but_straight_angle"] += 1
                    if len(samples) < 8:
                        samples.append((si, f, v*3.6, st["angle"], abs(st["curv"]), ay_s, ay_c))
        st["f"] += 1
    del lr

n = tot["n"]
print(f"激活帧: {n}")
print(f"弯道帧(模型|ay|>0.5): {tot['in_curv']} ({100*tot['in_curv']/max(n,1):.1f}%)")
print(f"【关键】弯道中但方向盘已回正(|ay_s|<0.2): {tot['curv_but_straight_angle']} ({100*tot['curv_but_straight_angle']/max(tot['in_curv'],1):.0f}% of 弯道帧)")
print(f"\n代表帧（弯道中方向盘回正）：段/帧/vkmh/angle°/curv/ay_s/ay_c")
for s in samples:
    print(f"  段{s[0]} 帧{s[1]:>6} v={s[2]:>4.0f} angle={s[3]:>5.1f}° curv={s[4]:.4f} | ay_s={s[5]:.2f} ay_c={s[6]:.2f}")
print("\n结论：占比高 = 当前代码(angle)在弯道大部分时间已解除加速限制，而模型曲率认为还在弯里")
print("→ 改用 curvature 能让限制持续到车头真正转正（官方新版做法）")
