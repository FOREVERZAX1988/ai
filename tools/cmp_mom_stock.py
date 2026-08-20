#!/usr/bin/env python3
"""段7 97000-97700 窗口：OP代发(src=128) vs 原厂(src=2) 的 mom 对比
确认 mom 95↔0 跳变是"我们映射的台阶"还是"跟随原厂 stock_mom 波动"——决定死区方案是否有效"""
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
st = {"f": 0, "momO": -99, "momS": -99, "at": 0.0, "v": 0.0, "stock_mom": -99}
print(f"{'帧':>6} {'vEgo':>5} {'aTgt':>6} | {'OPmom(128)':>8} {'原厂mom(2)':>8} | 判断")
T0, T1 = 97000, 97700
for msg in lr:
    f = st["f"]
    if msg.which() == "carState":
        st["v"] = msg.carState.vEgo
    elif msg.which() == "longitudinalPlan":
        st["at"] = msg.longitudinalPlan.aTarget
    elif msg.which() == "can":
        for c in msg.can:
            if c.address == 269 and len(c.dat) >= 8:
                d = bytes(c.dat)
                mom = get_sig(d, A["ACC_Momentenanforderung"][0], A["ACC_Momentenanforderung"][1], False)
                if c.src == 128:
                    st["momO"] = mom
                elif c.src == 2:
                    st["momS"] = mom
    if T0 <= f <= T1 and f % 25 == 0:
        op, sp = st["momO"], st["momS"]
        tag = ""
        if abs(op - sp) <= 8:
            tag = "跟随原厂" if op == sp else ""
        elif op == 0 and sp > 60:
            tag = "←我们归零(原厂在给油)【我们侧台阶】"
        elif sp == 0 and op > 60:
            tag = "←原厂归零(我们在给油)【原厂滑行】"
        print(f"{f:>6} {st['v']*3.6:>5.1f} {st['at']:>+6.3f} | {op:>8.0f} {sp:>8.0f} | {tag}")
    st["f"] += 1
    if f > T1: break
del lr
print("\n判断：OPmom 与 原厂mom 几乎一致→我们跟随原厂（原厂自己在给油-滑行切换，死区无效）")
print("      OPmom=0 而 原厂mom>60 → 我们侧归零（死区有效）")
