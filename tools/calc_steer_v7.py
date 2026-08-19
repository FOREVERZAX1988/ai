#!/usr/bin/env python3
"""转向标定多route交叉验证 v7：00000002/00000004/00000049 分别标定 steerRatio，
检查跨route一致性（各route中位接近→可靠；差异大→不可靠）。
gyro偏置每route独立标定（静止帧中位）。"""
import sys, glob, math
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
import numpy as np

WB = 2.896

def load(route):
    files = sorted(glob.glob(f"/data/media/0/realdata/{route}--*--rlog.zst"))
    dirs = sorted(glob.glob(f"/data/media/0/realdata/{route}--*/rlog.zst"))
    paths = dirs + files
    cs_rows, gyro_rows = [], []
    for p in paths:
        try:
            lr = LogReader(p)
        except Exception:
            continue
        n = 0
        for msg in lr:
            n += 1
            if n > 8000: break
            w = msg.which()
            if w == "carState":
                c = msg.carState
                cs_rows.append((msg.logMonoTime/1e9, c.vEgo, c.steeringAngleDeg))
            elif w == "gyroscope":
                g = msg.gyroscope
                try:
                    gyro_rows.append((msg.logMonoTime/1e9, g.gyroUncalibrated.v[2] if hasattr(g, 'gyroUncalibrated') else g.gyro.v[2]))
                except Exception:
                    pass
        del lr
    return cs_rows, gyro_rows

def smooth(x, w=10):
    k = np.ones(w)/w
    return np.convolve(x, k, mode="same")

results = {}
for route in ["00000002--5284e8b7f1", "00000004--915ebf086f", "00000049--ac8e2bc7b1"]:
    cs_rows, gyro_rows = load(route)
    if len(cs_rows) < 100 or len(gyro_rows) < 100:
        print(f"{route}: 数据不足 (cs={len(cs_rows)} gyro={len(gyro_rows)})")
        continue
    # gyro 偏置：该route静止帧（v<0.5）gyro.z 中位
    gyro_t = np.array([r[0] for r in gyro_rows]); gyro_z = np.array([r[1] for r in gyro_rows])
    cs_t = np.array([r[0] for r in cs_rows]); cs_v = np.array([r[1] for r in cs_rows])
    cs_sa = np.array([r[2] for r in cs_rows])
    # 用 carState v<0.5 的时刻找 gyro 静止段（用时间对齐粗略判断）
    ig = np.searchsorted(gyro_t, cs_t[cs_v < 0.5][:50] if (cs_v < 0.5).sum() > 0 else cs_t[:1])
    bias = np.median(gyro_z[:max(ig.max()+100, 100)]) if len(ig) else 0.0124
    # 更稳：直接取前200帧（通常驻车）
    if len(gyro_z) > 200:
        bias = np.median(gyro_z[:200])
    gyro_z_s = smooth(gyro_z - bias)
    i = np.searchsorted(gyro_t, cs_t); i = np.clip(i, 0, len(gyro_t)-1)
    close = np.abs(gyro_t[i] - cs_t) < 0.05
    i = i[close]
    v, sa = cs_v[close], cs_sa[close]
    yr = gyro_z_s[i]
    dsa = np.abs(np.diff(sa, prepend=sa[0])) / 0.01
    dyr = np.abs(np.diff(yr, prepend=yr[0])) / 0.05
    steady = (dsa < 5.0) & (dyr < 0.05) & (v > 5) & (np.abs(sa) > 2) & (np.abs(yr) > 0.005)
    sub_v, sub_sa, sub_yr = v[steady], sa[steady], yr[steady]
    if len(sub_v) < 30:
        print(f"{route}: 稳态段不足 ({len(sub_v)})")
        continue
    curv = sub_yr / np.maximum(sub_v, 0.1)
    ratio = np.radians(sub_sa) / np.arctan(curv * WB)
    ok = (ratio > 5) & (ratio < 30) & (curv > 0.0003)
    r_ok = ratio[ok]
    print(f"\n=== {route} ===")
    print(f"  gyro偏置={bias:.4f} 稳态段={len(sub_v)} 有效样本={len(r_ok)}")
    if len(r_ok) > 30:
        med = np.median(r_ok)
        results[route] = med
        print(f"  steerRatio: 中位={med:.2f} 均值={r_ok.mean():.2f}±{r_ok.std():.2f} p25={np.percentile(r_ok,25):.2f} p75={np.percentile(r_ok,75):.2f}")
        sv = sub_v[ok]
        for v0, v1 in [(5,10),(10,15),(15,20),(20,30)]:
            m2 = (sv > v0) & (sv <= v1)
            if m2.sum() > 15:
                print(f"    {v0}-{v1}m/s: {np.median(r_ok[m2]):.2f} (n={int(m2.sum())})")

print(f"\n=== 跨route一致性 ===")
if len(results) >= 2:
    meds = list(results.values())
    spread = max(meds) - min(meds)
    print(f"  各route中位: {results}")
    print(f"  极差: {spread:.2f} ({spread/np.mean(meds)*100:.0f}% of mean)")
    print(f"  → {'✅ 跨route一致（可靠）' if spread < 2.0 else '⚠️ 跨route差异大（不可靠，开关默认关等数据）'}")
    print(f"  综合中位: {np.median(meds):.2f}")
else:
    print("  ⚠️ 有效route不足，无法交叉验证")
