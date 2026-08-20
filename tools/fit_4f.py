#!/usr/bin/env python3
"""4f（8.20路试）拟合任务：
A. 坡度补偿拟合：v2公式 slope_oem=(espl-aEgo)/g*100 vs 真实坡度（匀速段 espl/g）
B. 转向角系数（steerRatio）拟合：ESP_Gierrate vs steeringAngleDeg 回归（分速度段）
C. 无车摇晃：lead 远窗口 aTarget 波动（"周边没车也加减速"定位）"""
import glob, sys, re, math
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
import numpy as np

DBC = "opendbc_repo/opendbc/dbc/vw_mlb.dbc"
dbc_text = open(DBC, encoding="latin-1").read()
def sig_def(name, msg_id):
    m = re.search(rf'^ SG_ {name} : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)', dbc_text, re.M)
    if not m: return None
    return (int(m.group(1)), int(m.group(2)), m.group(4)=='-', float(m.group(5)), float(m.group(6)))
ESPL = sig_def("ESP_Laengsbeschl", 257)
GIER = sig_def("ESP_Gierrate", 257)
def get_sig(dat, start, length, signed):
    if len(dat) <= (start + length - 1) // 8: return 0
    val = 0
    for i in range(length):
        byte = (start + i) // 8
        bit = (start + i) % 8
        if dat[byte] & (1 << bit): val |= (1 << i)
    if signed and val & (1 << (length - 1)): val -= (1 << length)
    return val

segs = sorted(glob.glob("/data/media/0/realdata/0000004f--*/rlog.zst"))
WHEELBASE = 2.81

# ============ A. 坡度补偿拟合 ============
print("="*70)
print("A. 坡度补偿拟合（全开段 7-14）")
print("   v2公式: slope_oem = (ESP_Laengsbeschl - aEgo)/9.81*100 (%坡度)")
print("   验证: 匀速段 slope_oem 应≈真实坡度(espl/g*100)")
print("="*70)
slope_samples = []
for si in range(7, 15):
    lr = LogReader(segs[si])
    st = {"f": 0, "v": 0.0, "a": 0.0, "espl": 0.0, "en": False}
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            cs = msg.carState
            st["v"] = cs.vEgo; st["a"] = cs.aEgo; st["en"] = cs.cruiseState.enabled
        elif msg.which() == "can":
            for c in msg.can:
                if c.address == 257 and len(c.dat) >= 8:
                    d = bytes(c.dat)
                    st["espl"] = get_sig(d, ESPL[0], ESPL[1], ESPL[2]) * ESPL[3] + ESPL[4]
        if st["en"] and st["v"] > 5.0 and abs(st["a"]) < 0.15 and f % 10 == 0:
            slope_oem = (st["espl"] - st["a"]) / 9.81 * 100.0
            true_slope = st["espl"] / 9.81 * 100.0
            slope_samples.append((true_slope, slope_oem, st["v"] * 3.6))
        st["f"] += 1
    del lr
if slope_samples:
    s = np.array(slope_samples)
    k, b = np.polyfit(s[:, 0], s[:, 1], 1)
    resid = s[:, 1] - (k * s[:, 0] + b)
    r2 = 1 - np.sum(resid**2) / np.sum((s[:, 1] - s[:, 1].mean())**2)
    print(f"样本: {len(s)}  真实坡度范围: [{s[:,0].min():.1f}%, {s[:,0].max():.1f}%]")
    print(f"回归: slope_oem = {k:.3f} × 真实坡度 + {b:.3f}   R²={r2:.3f}")
    print(f"（k≈1 且 b≈0 表示 v2 公式正确；k<1 低估补偿）")
    print(f"残差 std: {resid.std():.3f}%  (坡度估计噪声)")
    for lo, hi, nm in [(5, 15, "低速18-54km/h"), (15, 30, "中速54-108"), (30, 80, "高速>108")]:
        m = (s[:, 2] >= lo) & (s[:, 2] < hi)
        if m.sum() > 50:
            kk, bb = np.polyfit(s[m, 0], s[m, 1], 1)
            print(f"  {nm}: n={m.sum()} k={kk:.3f} b={bb:.3f}")

# ============ B. steerRatio 拟合 ============
print("\n" + "="*70)
print("B. 转向角系数（steerRatio）拟合（全部15段）")
print("   模型: steeringAngle = SR × atan(yaw/vEgo × 2.81)")
print("="*70)
samples = []
for si in range(15):
    lr = LogReader(segs[si])
    st = {"f": 0, "v": 0.0, "yaw": 0.0, "steer": 0.0}
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            cs = msg.carState
            st["v"] = cs.vEgo; st["steer"] = cs.steeringAngleDeg
        elif msg.which() == "can":
            for c in msg.can:
                if c.address == 257 and len(c.dat) >= 8:
                    d = bytes(c.dat)
                    st["yaw"] = get_sig(d, GIER[0], GIER[1], GIER[2]) * GIER[3] + GIER[4]
        # 稳定弯道窗口：|steer|>5°、|yaw|>1°/s、v>5m/s
        if abs(st["steer"]) > 5.0 and abs(st["yaw"]) > 1.0 and st["v"] > 5.0 and f % 5 == 0:
            yaw_rad = abs(st["yaw"]) * math.pi / 180.0
            curv = yaw_rad / st["v"]
            phi = math.atan(curv * WHEELBASE) * 180.0 / math.pi  # 前轮角(度)
            if phi > 0.3:
                samples.append((phi, abs(st["steer"]), st["v"] * 3.6))
        st["f"] += 1
    del lr
if samples:
    s = np.array(samples)
    print(f"样本: {len(s)}")
    for lo, hi, nm in [(0, 10, "0-36km/h"), (10, 20, "36-72km/h"), (20, 40, "72-144km/h"), (40, 100, ">144km/h")]:
        m = (s[:, 2] >= lo) & (s[:, 2] < hi)
        if m.sum() > 30:
            phi, sr = s[m, 0], s[m, 1]
            SR = np.sum(sr * phi) / np.sum(phi * phi)  # 过原点最小二乘
            pred = SR * phi
            rmse = np.sqrt(np.mean((sr - pred)**2))
            print(f"  {nm}: n={m.sum():>4}  steerRatio={SR:.2f}  RMSE={rmse:.2f}°")
    # 总体
    phi, sr = s[:, 0], s[:, 1]
    SR = np.sum(sr * phi) / np.sum(phi * phi)
    print(f"  总体: n={len(s)} steerRatio={SR:.2f}  (当前代码 16.2)")

# ============ C. 无车摇晃 ============
print("\n" + "="*70)
print("C. 无车摇晃：lead 远/无效 + 中速 + aTarget 波动（\"周边没车也加减速\"）")
print("="*70)
cands = []
for si in range(15):
    lr = LogReader(segs[si])
    st = {"f": 0, "v": 0.0, "at": 0.0, "lead_d": 999.0, "lead_prob": 0.0, "en": False}
    win = []
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            cs = msg.carState
            st["v"] = cs.vEgo; st["en"] = cs.cruiseState.enabled
        elif msg.which() == "longitudinalPlan":
            st["at"] = msg.longitudinalPlan.aTarget
        elif msg.which() == "modelV2":
            if len(msg.modelV2.leadsV3) > 0:
                st["lead_d"] = msg.modelV2.leadsV3[0].x[0]
                st["lead_prob"] = msg.modelV2.leadsV3[0].prob
        # 无车窗口：lead 远(>60m)或低prob + v>8m/s + 激活
        no_car = st["lead_d"] > 60.0 or st["lead_prob"] < 0.3
        if st["en"] and st["v"] > 8.0 and no_car and f % 10 == 0:
            win.append((f, st["at"]))
            if len(win) > 100: win.pop(0)
            if len(win) == 100:
                ats = [x[1] for x in win]
                span = max(ats) - min(ats)
                flips = sum(1 for i in range(1, len(ats)) if (ats[i] > 0.1) != (ats[i-1] > 0.1))
                if span > 0.6 or flips > 5:
                    cands.append((si, win[0][0], span, flips, st["v"]*3.6, st["lead_d"]))
                    win = []
        st["f"] += 1
    del lr
if cands:
    print(f"无车但 aTarget 明显波动窗口: {len(cands)} 个")
    for si, f0, span, flips, v, ld in cands[:15]:
        print(f"  段{si} 帧{f0}: aTarget跨度={span:.2f} 正负翻转={flips}次 v={v:.0f}km/h lead={ld:.0f}m")
else:
    print("无候选（无车时 aTarget 稳定）——摇晃另有来源，需进一步定位")
