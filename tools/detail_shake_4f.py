#!/usr/bin/env python3
"""细看段8 两个关键窗口：
A. 帧13000-13500 (w=26)：espl std=0.177 + verz72%负 + mom std49.5 —— 疑似路面抖→摇晃
B. 帧23500-24000 (w=47)：espl std=0.024(干净) + mom std67 —— 疑似跟车
逐帧看 espl/verzO/momO 形态，判断"来回晃" vs "单次事件"""
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
lr = LogReader(segs[8])
st = {"f": 0, "v": 0.0, "en": False, "espl": 0.0, "verzO": 99, "momO": -99, "aTgt": 0.0}
for msg in lr:
    f = st["f"]
    if msg.which() == "carState":
        st["v"] = msg.carState.vEgo
        st["en"] = msg.carState.cruiseState.enabled
    elif msg.which() == "longitudinalPlan":
        st["aTgt"] = msg.longitudinalPlan.aTarget
    elif msg.which() == "can":
        for c in msg.can:
            if c.address == 257 and len(c.dat) >= 6:
                d = bytes(c.dat)
                st["espl"] = get_sig(d, ESPL[0], ESPL[1], ESPL[2]) * ESPL[3] + ESPL[4]
            elif c.address == 269 and c.src == 128 and len(c.dat) >= 8:
                d = bytes(c.dat)
                st["verzO"] = get_sig(d, A["ACC_Verz_anf"][0], A["ACC_Verz_anf"][1], A["ACC_Verz_anf"][2]) * 0.005 - 7.22
                st["momO"] = get_sig(d, A["ACC_Momentenanforderung"][0], A["ACC_Momentenanforderung"][1], A["ACC_Momentenanforderung"][2])
    for label, (a, b) in {"A(13000-13500)": (13000, 13500), "B(23500-24000)": (23500, 24000)}.items():
        if f == a:
            print(f"\n===== 窗口{label} ===== ({a}-{b}, 步长10帧)")
            print(f"{'帧':>6} {'v':>5} | {'espl':>6} | {'aTgt':>6} {'verzO':>6} {'momO':>5}")
    if (13000 <= f <= 13500 or 23500 <= f <= 24000) and f % 10 == 0:
        print(f"{f:>6} {st['v']*3.6:>5.0f} | {st['espl']:>6.3f} | {st['aTgt']:>6.2f} {st['verzO']:>6.2f} {st['momO']:>5.0f}")
    st["f"] += 1
    if f > 24000: break
del lr
