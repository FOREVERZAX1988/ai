#!/usr/bin/env python3
"""坡度信号抖动 vs 摇晃指标 —— 验证"坡度敏感→补偿增减→摇晃"假设
对比：全开段（8/11，补偿开） vs 全关段（3/4，补偿关）
ESP_02(257).ESP_Laengsbeschl 40|14@0+ scale0.01 —— 车体纵向加速度（含坡度重力分量+车辆加减速）
匀速窗口里 espl ≈ g*sin(坡度)，其抖动 = 坡度信号噪声
摇晃指标：verzO负帧率 / momO翻转 / momO std"""
import glob, sys, re
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

DBC = "opendbc_repo/opendbc/dbc/vw_mlb.dbc"
dbc_text = open(DBC, encoding="latin-1").read()
def sig_def(name, msg_id):
    m = re.search(rf'^ SG_ {name} : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)', dbc_text, re.M)
    if not m: return None
    return (int(m.group(1)), int(m.group(2)), m.group(4)=='-', float(m.group(5)), float(m.group(6)))
ESPL = sig_def("ESP_Laengsbeschl", 257)
A = {n: sig_def(n, 269) for n in ["ACC_Verz_anf", "ACC_Momentenanforderung"]}
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
print(f"ESP_Laengsbeschl@257: {ESPL[:3] if ESPL else None}")

def analyze(si, name):
    lr = LogReader(segs[si])
    st = {"f": 0, "v": 0.0, "pv": 0.0, "en": False,
          "espl": 0.0, "verzO": 99, "momO": -99, "pmom": -99}
    W = {}
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            st["v"] = msg.carState.vEgo
            st["en"] = msg.carState.cruiseState.enabled
        elif msg.which() == "can":
            for c in msg.can:
                if c.address == 257 and len(c.dat) >= 6:
                    d = bytes(c.dat)
                    st["espl"] = get_sig(d, ESPL[0], ESPL[1], ESPL[2]) * ESPL[3] + ESPL[4]
                elif c.address == 269 and c.src == 128 and len(c.dat) >= 8:
                    d = bytes(c.dat)
                    st["verzO"] = get_sig(d, A["ACC_Verz_anf"][0], A["ACC_Verz_anf"][1], A["ACC_Verz_anf"][2]) * 0.005 - 7.22
                    st["momO"] = get_sig(d, A["ACC_Momentenanforderung"][0], A["ACC_Momentenanforderung"][1], A["ACC_Momentenanforderung"][2])
        # 匀速行驶窗口（激活 & v>5m/s & |dv|<1.5m/s2）
        if st["en"] and st["v"] > 5.0 and abs(st["v"] - st["pv"]) < 1.5:
            w = f // 500  # 5s 窗口
            if w not in W:
                W[w] = {"espl": [], "v": [], "verz_neg": 0, "mom": [], "flip": 0, "pmom": None}
            W[w]["espl"].append(st["espl"])
            W[w]["v"].append(st["v"])
            if st["verzO"] < 0:
                W[w]["verz_neg"] += 1
            if st["momO"] >= 0:
                W[w]["mom"].append(st["momO"])
                if W[w]["pmom"] is not None and abs(st["momO"] - W[w]["pmom"]) > 8:
                    W[w]["flip"] += 1
                W[w]["pmom"] = st["momO"]
        st["pv"] = st["v"]
        st["f"] += 1
    del lr
    # 输出：窗口列表（5s）——espl std（坡度噪声）+ verz负帧率 + mom翻转
    print(f"\n=== {name} (段{si})：匀速窗口坡度噪声 vs 摇晃指标 ===")
    print(f"{'窗口(s)':>9} {'n':>4} {'espl均值':>8} {'espl std':>8} | {'verz负帧%':>8} {'mom翻转/10s':>10} {'mom std':>7}")
    for w in sorted(W.keys()):
        d = W[w]
        n = len(d["espl"])
        if n < 100: continue
        espl_mean = sum(d["espl"]) / n
        espl_std = (sum((x - espl_mean) ** 2 for x in d["espl"]) / n) ** 0.5
        mom = d["mom"]
        mom_std = (sum((x - sum(mom) / len(mom)) ** 2 for x in mom) / len(mom)) ** 0.5 if mom else 0
        vn_pct = 100 * d["verz_neg"] / n
        print(f"{w*0.05:>8.0f}s {n:>4} {espl_mean:>8.3f} {espl_std:>8.3f} | {vn_pct:>7.1f}% {d['flip']:>10} {mom_std:>7.1f}")

analyze(8, "全开-城市")
analyze(3, "全关-对照")
analyze(11, "全开-城市2")
