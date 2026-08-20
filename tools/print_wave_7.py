#!/usr/bin/env python3
"""打印段7 帧97282 附近的 mom/aTarget/vEgo 波形（每0.3s采样），确认开合形态"""
import glob, sys, re
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

DBC = "opendbc_repo/opendbc/dbc/vw_mlb.dbc"
dbc_text = open(DBC, encoding="latin-1").read()
def sig_def(name, msg_id):
    m = re.search(rf'^ SG_ {name} : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)', dbc_text, re.M)
    if not m: return None
    return (int(m.group(1)), int(m.group(2)), m.group(4)=='-', float(m.group(5)), float(m.group(6)))
A = {n: sig_def(n, 269) for n in ["ACC_Momentenanforderung", "ACC_Verz_anf"]}
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
lr = LogReader(segs[7])
st = {"f": 0, "v": 0.0, "at": 0.0, "mom": 0, "verz": 0.0, "vset": 0.0}
T0, T1 = 97000, 97700  # 段7 振荡窗口
print(f"段7 帧{T0}-{T1}（每0.3s采样）: 时间  vEgo   vSet  aTarget   mom  verz")
last = [None]*10
for msg in lr:
    f = st["f"]
    if msg.which() == "carState":
        cs = msg.carState
        st["v"] = cs.vEgo
        st["vset"] = cs.cruiseState.speed
    elif msg.which() == "longitudinalPlan":
        st["at"] = msg.longitudinalPlan.aTarget
    elif msg.which() == "can":
        for c in msg.can:
            if c.address == 269 and c.src == 128 and len(c.dat) >= 8:
                d = bytes(c.dat)
                st["mom"] = get_sig(d, A["ACC_Momentenanforderung"][0], A["ACC_Momentenanforderung"][1], False)
                st["verz"] = get_sig(d, A["ACC_Verz_anf"][0], A["ACC_Verz_anf"][1], True) * 0.005 - 7.22
    if f == T0: print(f"  --- 进入窗口 ---")
    if T0 <= f <= T1 and f % 30 == 0:
        print(f"  {f:>6}  {st['v']*3.6:>5.1f} {st['vset']*3.6:>5.1f} {st['at']:>+7.3f} {st['mom']:>4.0f} {st['verz']:>+5.2f}")
    st["f"] += 1
    if f > T1: break
del lr
