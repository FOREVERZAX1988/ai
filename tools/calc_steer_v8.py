#!/usr/bin/env python3
"""转向标定 v2：用 ESP_Gierrate（原厂横摆角速度，度/秒+VZ符号）标定 steerRatio
对比 v7（gyro.z 设备陀螺仪）——期望解决跨 route 极差 22% 不可靠问题
方法：curv = yawRate/v；delta = atan(curv*WB)；steerRatio = steerAngle/delta
数据：carState(steerAngleDeg/vEgo/aEgo) 与 can ESP_02(ESP_Gierrate/VZ) 时间配对"""
import re, glob, sys, os, math
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
import numpy as np

def get_sig(dat, start, length, signed=False):
    val = 0
    for i in range(length):
        byte = (start + i) // 8
        bit = (start + i) % 8
        if dat[byte] & (1 << bit):
            val |= (1 << i)
    if signed and val & (1 << (length - 1)):
        val -= (1 << length)
    return val

WB = 2.81  # Macan 轴距 m（values.py 确认）
GID = 257  # ESP_02

ROUTES = ["00000001", "00000002", "00000004", "00000005", "00000049"]
# 00000049 段目录格式且段0/1为空——从段2开始；其他 route 扁平格式
flat_paths = {}
dir_paths = {}
for r in ROUTES:
    flat_paths[r] = sorted(glob.glob(f"/data/media/0/realdata/{r}--*--rlog.zst"))
    d = sorted(glob.glob(f"/data/media/0/realdata/{r}--*/rlog.zst"))
    # 只保留段号>=2（00000049 段0/1为空）
    d = [p for p in d if int(os.path.basename(os.path.dirname(p)).split("--")[-1]) >= 2]
    dir_paths[r] = d

print("扫描 routes:", {r: f"扁平{len(flat_paths[r])}+目录{len(dir_paths[r])}" for r in ROUTES})

all_results = {}
for r in ROUTES:
    paths = (flat_paths[r] + dir_paths[r])[:5]
    ratios = []
    for p in paths:
        try:
            lr = LogReader(p)
        except Exception:
            continue
        st = {"steer": 0.0, "v": 0.0, "a": 0.0}
        for msg in lr:
            if msg.which() == "carState":
                st["steer"] = msg.carState.steeringAngleDeg
                st["v"] = msg.carState.vEgo
                st["a"] = msg.carState.aEgo
            elif msg.which() == "can":
                for c in msg.can:
                    if c.address == GID:
                        yaw_deg = get_sig(bytes(c.dat), 40, 14) * 0.01 * (1, -1)[get_sig(bytes(c.dat), 54, 1)]
                        v = st["v"]
                        # 稳态过滤：v>5m/s、有弯(|yaw|>0.5°/s)、非直行(|steer|>1°)、无加减速(|a|<0.5)
                        if v > 5 and abs(yaw_deg) > 0.5 and abs(st["steer"]) > 1 and abs(st["a"]) < 0.5:
                            curv = math.radians(yaw_deg) / v
                            delta = math.atan(curv * WB)
                            sr = math.radians(st["steer"]) / delta
                            if 5 < sr < 40:  # 合理性范围
                                ratios.append(sr)
        del lr
    all_results[r] = ratios
    if ratios:
        a = np.array(ratios)
        print(f"\n{r}: n={len(a)} 中位={np.median(a):.2f} 均值={a.mean():.2f} std={a.std():.2f} "
              f"P25={np.percentile(a,25):.2f} P75={np.percentile(a,75):.2f} 范围[{a.min():.1f},{a.max():.1f}]")
    else:
        print(f"\n{r}: 无有效样本")

# 汇总：跨 route 一致性
valid = {r: a for r, a in all_results.items() if len(a) > 20}
if len(valid) >= 2:
    medians = [np.median(a) for a in valid.values()]
    print(f"\n=== 跨 route 一致性（v2 原厂 Gierrate）===")
    print(f"各 route 中位: {[f'{m:.2f}' for m in medians]}")
    print(f"极差: {max(medians)-min(medians):.2f} ({max(medians)-min(medians):.1f}%)")
    print(f"对比 v7(gyro.z): 15.89/17.98/19.86 极差 3.97 (22%)")
    print(f"总体中位: {np.median(list(valid.values())):.2f}")
else:
    print("有效 route 不足，无法交叉验证")
