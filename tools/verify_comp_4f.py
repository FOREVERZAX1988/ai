#!/usr/bin/env python3
"""验证 4f 坡度补偿是否生效 + 无车振荡窗口定位
① 补偿生效判定：0.5s 窗口内 espl 变化 vs mom 变化 相关性（生效=正相关显著）
② 无车振荡：lead 无效时 aTgt 的 std（>0.12 视为振荡）"""
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
A = {n: sig_def(n, 269) for n in ["ACC_Momentenanforderung"]}
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

def analyze(si):
    lr = LogReader(segs[si])
    st = {"f": 0, "v": 0.0, "en": False, "espl": 0.0, "momO": -99,
          "aTgt": 0.0, "lead_d": -1.0, "gas": False}
    pairs = []   # (Δespl, Δmom) 每50帧窗口
    osc = []     # 无 lead 振荡窗口
    buf = []     # 最近150帧 (f, aTgt, lead_d)
    win = {"espl": [], "mom": []}
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            cs = msg.carState
            st["v"] = cs.vEgo
            st["en"] = cs.cruiseState.enabled
            st["gas"] = cs.gasPressed
            st["lead_d"] = -1.0
        elif msg.which() == "longitudinalPlan" and st["en"]:
            st["aTgt"] = msg.longitudinalPlan.aTarget
        elif msg.which() == "can":
            for c in msg.can:
                if c.address == 257 and len(c.dat) >= 6:
                    d = bytes(c.dat)
                    st["espl"] = get_sig(d, ESPL[0], ESPL[1], ESPL[2]) * ESPL[3] + ESPL[4]
                elif c.address == 269 and c.src == 128 and len(c.dat) >= 8:
                    d = bytes(c.dat)
                    st["momO"] = get_sig(d, A["ACC_Momentenanforderung"][0], A["ACC_Momentenanforderung"][1], A["ACC_Momentenanforderung"][2])
        if st["en"] and st["v"] > 2.0 and not st["gas"]:
            win["espl"].append(st["espl"])
            win["mom"].append(st["momO"])
            buf.append((f, st["aTgt"], st["lead_d"]))
            if len(buf) > 150: buf.pop(0)
        if f % 50 == 0 and len(win["espl"]) > 10:
            pairs.append((max(win["espl"]) - min(win["espl"]), max(win["mom"]) - min(win["mom"])))
            win = {"espl": [], "mom": []}
        # 无 lead 振荡检测
        if len(buf) == 150 and f % 25 == 0:
            if True:
                at = [x[1] for x in buf]
                m = sum(at) / len(at)
                s = (sum((x - m) ** 2 for x in at) / len(at)) ** 0.5
                if s > 0.12:
                    osc.append((buf[0][0], buf[-1][0], round(m, 3), round(s, 3), round(max(at) - min(at), 3)))
        st["f"] += 1
    del lr
    # 相关性（Δespl 大时 Δmom 是否大）
    big_espl = [(a, b) for a, b in pairs if a > 0.15]
    corr_espl_mom = []
    if len(pairs) > 10:
        es = [a for a, _ in pairs]; mo = [b for _, b in pairs]
        me = sum(es) / len(es); mm = sum(mo) / len(mo)
        num = sum((a - me) * (b - mm) for a, b in pairs)
        den = (sum((a - me) ** 2 for a in es) * sum((b - mm) ** 2 for b in mo)) ** 0.5
        corr = num / den if den > 0 else 0
    else:
        corr = 0
    print(f"段{si}: 窗口数={len(pairs)} esplΔ>0.15窗口={len(big_espl)} | 其中 momΔ>15 的={sum(1 for a, b in big_espl if b > 15)} | 相关性={corr:.2f}")
    if big_espl:
        print(f"    esplΔ>0.15 的窗口示例: {[(round(a,2), round(b)) for a, b in big_espl[:8]]}")
    if osc:
        print(f"    无车aTgt振荡窗口 {len(osc)} 个: {[f'{a/100:.0f}-{b/100:.0f}s(aTgt均值{m:.2f} std{s:.2f} 峰峰{p:.2f})' for a, b, m, s, p in osc[:6]]}")
    return pairs, osc

print("=== ① 补偿生效验证（esplΔ vs momΔ 相关性）===")
print("（若补偿生效：espl 跳 → mom 同步跳，相关性>0.4 且 esplΔ>0.15 的窗口 momΔ 普遍>15）")
for si in [7, 8, 9, 11, 12, 13, 14]:
    try:
        analyze(si)
    except Exception as e:
        print(f"段{si} 错误: {e}")
