#!/usr/bin/env python3
"""坡度信号重新验算：用 controlsext 实际公式 n·acc-s_ref 在静止帧验证（应≈0）
上次误判根因：verify_slope_comp 用 arctan2(-g_x,sqrt(g_y²+g_z²)) 算的是设备安装倾角（86°），
不是车辆坡度——正确公式是 n·acc - s_ref（车辆前向投影与静止基准之差）。"""
import sys, glob
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
import numpy as np

N = (0.4571, -0.0079, -0.7667)
S_REF = 4.0412
G = 9.81

paths = sorted(glob.glob("/data/media/0/realdata/00000049--ac8e2bc7b1--*/rlog.zst"))
cs_rows, acc_rows = [], []
for p in paths:
    try:
        lr = LogReader(p)
    except Exception:
        continue
    n = 0
    for msg in lr:
        n += 1
        if n > 5000: break
        w = msg.which()
        if w == "carState":
            c = msg.carState
            cs_rows.append((msg.logMonoTime/1e9, c.vEgo))
        elif w == "accelerometer":
            a = msg.accelerometer
            acc_rows.append((msg.logMonoTime/1e9, a.acceleration.v[0], a.acceleration.v[1], a.acceleration.v[2]))
    del lr
cs_t = np.array([r[0] for r in cs_rows]); cs_v = np.array([r[1] for r in cs_rows])
acc_t = np.array([r[0] for r in acc_rows]); acc_d = np.array([r[1:] for r in acc_rows])
i = np.searchsorted(acc_t, cs_t); i = np.clip(i, 0, len(acc_t)-1)
close = np.abs(acc_t[i] - cs_t) < 0.1
i = i[close]
v = cs_v[close]; acc = acc_d[i]
print(f"对齐样本: {len(v)}")

# 静止帧（v<0.5）坡度信号
still = v < 0.5
if still.sum() > 50:
    s = N[0]*acc[still,0] - N[1]*acc[still,1] + N[2]*acc[still,2]  # 注意：n_y=-0.0079 → -0.0079*ay = -N[1]*ay
    # 用 controlsext 同样公式：0.4571*ax - 0.0079*ay - 0.7667*az
    s = 0.4571*acc[still,0] - 0.0079*acc[still,1] - 0.7667*acc[still,2]
    slope_still = (s - S_REF) / G * 100
    print(f"静止帧: {int(still.sum())}帧")
    print(f"  坡度信号(controlsext公式): 中位={np.median(slope_still):+.2f}% 均值={slope_still.mean():+.2f}±{slope_still.std():.2f}%")
    print(f"  范围 [{slope_still.min():+.1f}, {slope_still.max():+.1f}]%")
    print(f"  → 静止坡度应≈0：{'✅ 有效' if abs(np.median(slope_still)) < 1.0 else '❌ 异常'}")

# 动态帧：上坡/下坡区分（v>5）
dyn = v > 5
if dyn.sum() > 100:
    s = 0.4571*acc[dyn,0] - 0.0079*acc[dyn,1] - 0.7667*acc[dyn,2]
    slope_dyn = (s - S_REF) / G * 100
    print(f"\n动态帧: {int(dyn.sum())}帧 坡度分布: 中位={np.median(slope_dyn):+.1f}% std={slope_dyn.std():.1f}%")
    up = slope_dyn > 2; down = slope_dyn < -2
    print(f"  上坡(>2%): {int(up.sum())}帧({up.sum()/dyn.sum()*100:.0f}%) 下坡(<-2%): {int(down.sum())}帧({down.sum()/dyn.sum()*100:.0f}%)")
    print(f"  → {'✅ 有坡道数据' if up.sum() > 100 and down.sum() > 100 else '⚠️ 坡道样本少'}")
