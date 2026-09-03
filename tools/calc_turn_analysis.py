#!/usr/bin/env python3
"""弯道能力分析：原厂弯道需求 vs OP 输出能力（0接管大弯可行性评估）
数据：carState(steeringAngleDeg/vEgo/aEgo) + ESP_02(Gierrate/VZ→曲率) + LH_EPS_03(EPS_Lenkmoment→转向扭矩需求)
统计：弯道(|yaw|>1°/s)按速度段分布的 曲率/EPS扭矩/转向角 —— 判断 OP 扭矩控制参数能否覆盖"""
import glob, sys, os, math
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

# 报文：ESP_02=257(ESP_Gierrate 40|14 度/秒, VZ 54|1), LH_EPS_03 报文ID查
LH_EPS_ID = None
dbc = open("opendbc_repo/opendbc/dbc/vw_mlb.dbc", encoding="latin-1").read()
for m in __import__("re").finditer(r'^BO_ (\d+) LH_EPS_03', dbc, __import__("re").M):
    LH_EPS_ID = int(m.group(1))
print(f"LH_EPS_03 报文ID: {LH_EPS_ID}")

BINS = [(0,5),(5,15),(15,25),(25,40),(40,70),(70,200)]
def bin_idx(v):
    for i,(lo,hi) in enumerate(BINS):
        if lo <= v < hi: return i
    return -1

# 00000049 高速 + 00000002 低速城市 + 00000004
# 00000049 低速挪车段、00000002 城市段、00000004 高速段(11,13-19,45)
_49 = sorted(glob.glob("/data/media/0/realdata/00000049--*/rlog.zst"))[2:12]
_02 = glob.glob("/data/media/0/realdata/00000002--*--*/rlog.zst")[:8]
_04_all = glob.glob("/data/media/0/realdata/00000004--*--*/rlog.zst")
_04 = [_04_all[i] for i in [11,13,14,15,16,17,18,19,45] if i < len(_04_all)]
scan_routes = {"00000049(低速挪车)": _49, "00000002(城市)": _02, "00000004(高速)": _04}
stats = {r: {i: {"curv": [], "eps": [], "steer": [], "v": []} for i in range(len(BINS))} for r in scan_routes}
for r, paths in scan_routes.items():
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
                    if c.address == 257:
                        yaw = get_sig(bytes(c.dat), 40, 14) * 0.01 * (1, -1)[get_sig(bytes(c.dat), 54, 1)]
                        v = st["v"]
                        if abs(yaw) > 0.3 and v > 1:  # 弯道（高速缓弯阈值0.3°/s）
                            curv = math.radians(abs(yaw)) / max(v, 1.0)
                            bi = bin_idx(v)
                            if bi >= 0:
                                stats[r][bi]["curv"].append(curv)
                                stats[r][bi]["v"].append(v)
                                stats[r][bi]["steer"].append(abs(st["steer"]))
                    elif LH_EPS_ID and c.address == LH_EPS_ID:
                        v = st["v"]
                        bi = bin_idx(v)
                        if bi >= 0:
                            eps = get_sig(bytes(c.dat), 40, 10) * 0.01 * (1, -1)[get_sig(bytes(c.dat), 55, 1)]  # EPS_Lenkmoment 40|10 centiNm→Nm + VZ
                            stats[r][bi]["eps"].append(eps)
        del lr

print(f"\n{'route':<10}{'速度段':<10}{'弯帧':>6}{'曲率中位':>9}{'曲率P90':>9}{'EPS扭矩中位':>11}{'EPS P90':>9}{'转向角中位':>10}")
for r in scan_routes:
    for i, (lo, hi) in enumerate(BINS):
        s = stats[r][i]
        n = len(s["curv"])
        if n < 10: continue
        curv = np.array(s["curv"]); eps = np.array(s["eps"]); steer = np.array(s["steer"])
        eps_m = np.median(eps) if len(eps) else 0
        eps_p90 = np.percentile(eps, 90) if len(eps) else 0
        print(f"{r:<10}{f'{lo}-{hi}km/h':<10}{n:>6}{np.median(curv)*1000:>9.1f}{np.percentile(curv,90)*1000:>9.1f}{eps_m:>11.2f}{eps_p90:>9.2f}{np.median(steer):>10.1f}")
