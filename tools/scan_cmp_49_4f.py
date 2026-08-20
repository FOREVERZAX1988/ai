#!/usr/bin/env python3
"""对比 00000049（官方master OP纵向）vs 0000004f（我们 macan-long-0820）：
加速度幅度（aTarget分布）+ 实际jerk（ESP微分）——看我们的纵向控制是否比官方激进"""
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
def get_sig(dat, start, length, signed):
    if len(dat) <= (start + length - 1) // 8: return 0
    val = 0
    for i in range(length):
        byte = (start + i) // 8
        bit = (start + i) % 8
        if dat[byte] & (1 << bit): val |= (1 << i)
    if signed and val & (1 << (length - 1)): val -= (1 << length)
    return val

def analyze(route, fmt, label):
    if fmt == "flat":
        segs = sorted(glob.glob(f"/data/media/0/realdata/{route}--*--rlog.zst"))
    else:
        segs = sorted(glob.glob(f"/data/media/0/realdata/{route}--*/rlog.zst"))
    R = {"n": 0, "a_gt10": 0, "a_gt12": 0, "a_gt15": 0, "jk_gt2": 0,
         "espl": [], "prev_espl": None, "prev_f": None}
    for p in segs[:12]:
        try:
            lr = LogReader(p)
        except Exception:
            continue
        st = {"f": 0, "en": False, "at": 0.0, "espl": 0.0}
        for msg in lr:
            f = st["f"]
            if msg.which() == "carState":
                st["en"] = msg.carState.cruiseState.enabled
            elif msg.which() == "longitudinalPlan" and st["en"]:
                st["at"] = msg.longitudinalPlan.aTarget
                R["n"] += 1
                if st["at"] > 1.0: R["a_gt10"] += 1
                if st["at"] > 1.2: R["a_gt12"] += 1
                if st["at"] > 1.5: R["a_gt15"] += 1
            elif msg.which() == "can":
                for c in msg.can:
                    if c.address == 257 and len(c.dat) >= 6 and st["en"]:
                        d = bytes(c.dat)
                        a = get_sig(d, ESPL[0], ESPL[1], ESPL[2]) * ESPL[3] + ESPL[4]
                        if R["prev_espl"] is not None and R["prev_f"] is not None:
                            dt = (f - R["prev_f"]) / 100.0
                            if 0.05 < dt < 0.2:
                                jk = abs((a - R["prev_espl"]) / dt)
                                if jk > 2.0: R["jk_gt2"] += 1
                        R["prev_espl"] = a
                        R["prev_f"] = f
            st["f"] += 1
            if st["f"] > 60000: break
        del lr
    n = R["n"]
    print(f"\n=== {label} ({route}) ===")
    print(f"激活帧(含aTarget): {n}")
    if n:
        print(f"  加速度幅度: >1.0 占 {100*R['a_gt10']/n:.1f}% | >1.2 占 {100*R['a_gt12']/n:.1f}% | >1.5 占 {100*R['a_gt15']/n:.1f}%")
    jn = R["n"]
    print(f"  实际jerk>2.0 帧: {R['jk_gt2']} (占比以激活帧计 {100*R['jk_gt2']/jn:.2f}%)" if jn else "  (无激活帧)")

analyze("00000049", "dir", "官方master（OP纵向，2025.003）")
analyze("0000004f", "dir", "我们 macan-long-0820（8.20路试）")
