#!/usr/bin/env python3
"""扫 4f 全开段（7-14）找"快速加减速反复切换"事件：
aTarget 在 1.5s 内 正→负→正 翻转（或 |ΔaTgt|>0.8 快速来回）→ 体感摇晃候选
同时统计 espl（坡度）在这些窗口的抖动"""
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

segs = sorted(glob.glob("/data/media/0/realdata/0000004f--*/rlog.zst"))
for si in range(7, 15):
    lr = LogReader(segs[si])
    buf = []  # 最近 200 帧的 (f, aTgt, espl)
    flips = []
    st = {"f": 0, "en": False, "espl": 0.0}
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            st["en"] = msg.carState.cruiseState.enabled
        elif msg.which() == "longitudinalPlan" and st["en"]:
            a = msg.longitudinalPlan.aTarget
            buf.append((f, a, st["espl"]))
            if len(buf) > 200: buf.pop(0)
            # 检测 1.5s 内 正→负→正 翻转（±0.2 阈值）
            if len(buf) >= 10:
                ref = buf[-1][0] - 150
                seg = [x for x in buf if x[0] >= ref]
                signs = [1 if x[1] > 0.25 else (-1 if x[1] < -0.25 else 0) for x in seg]
                # 找 0→±→∓→± 模式
                s = [x for x in signs if x != 0]
                if len(s) >= 4 and len(set(s)) >= 2:
                    last = [x for x in buf if x[0] >= f - 300]
                    if last and not flips or (flips and f - flips[-1][0] > 500):
                        flips.append((f, min(signs), max(signs), a, st["espl"]))
        elif msg.which() == "can":
            for c in msg.can:
                if c.address == 257 and len(c.dat) >= 6:
                    d = bytes(c.dat)
                    st["espl"] = get_sig(d, ESPL[0], ESPL[1], ESPL[2]) * ESPL[3] + ESPL[4]
        st["f"] += 1
        if f > 80000: break
    del lr
    print(f"段{si}: 加减速翻转候选 {len(flips)} 个" + (f"  {[(f, f'v={None}') for f, *_ in flips[:6]]}" if flips else ""))
