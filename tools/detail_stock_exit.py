#!/usr/bin/env python3
"""深挖"踩油门→原厂退出"事件（4e 段2 帧34359）：
确认机制——踩油门期间我们代发的 verzO（是否发了刹车请求=与原厂超驰矛盾）
vs 力矩 momO（是否照发巡航值）→ 找原厂退出（stS 4→0）的触发点"""
import glob, sys, re
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

DBC = "opendbc_repo/opendbc/dbc/vw_mlb.dbc"
dbc_text = open(DBC, encoding="latin-1").read()
def sig_def(name, msg_id):
    m = re.search(rf'^ SG_ {name} : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)', dbc_text, re.M)
    if not m: return None
    return (int(m.group(1)), int(m.group(2)), m.group(4)=='-', float(m.group(5)), float(m.group(6)))
A = {n: sig_def(n, 269) for n in ["ACC_Status_ACC", "ACC_Momentenanforderung", "ACC_Verz_anf"]}
def get_sig(dat, start, length, signed):
    if len(dat) <= (start + length - 1) // 8: return 0
    val = 0
    for i in range(length):
        byte = (start + i) // 8
        bit = (start + i) % 8
        if dat[byte] & (1 << bit): val |= (1 << i)
    if signed and val & (1 << (length - 1)): val -= (1 << length)
    return val

segs = sorted(glob.glob("/data/media/0/realdata/0000004e--*/rlog.zst"))
lr = LogReader(segs[2])
st = {"f": 0, "gas": 0, "en": 0, "at": 0.0, "a": 0.0,
      "stO": -1, "stS": -1, "momO": 0, "momS": 0, "verzO": 99, "verzS": 99, "v": 0.0}
T0, T1 = 34200, 34950
print(f"4e 段2 事件深挖（踩油门34359起→退出34546，帧{T0}-{T1}，每5帧）")
print(f"{'帧':>6} {'gas':>3} {'en':>3} {'v':>4} | {'stO':>3} {'stS':>3} | {'momO':>4} {'momS':>4} {'verzO':>6} {'verzS':>6} {'aTgt':>5} {'aEgo':>5}")
for msg in lr:
    f = st["f"]
    if msg.which() == "carState":
        cs = msg.carState
        st["gas"] = cs.gasPressed
        st["en"] = cs.cruiseState.enabled
        st["a"] = cs.aEgo
        st["v"] = cs.vEgo
    elif msg.which() == "longitudinalPlan":
        st["at"] = msg.longitudinalPlan.aTarget
    elif msg.which() == "can":
        for c in msg.can:
            if c.address == 269 and len(c.dat) >= 8:
                d = bytes(c.dat)
                s = get_sig(d, A["ACC_Status_ACC"][0], A["ACC_Status_ACC"][1], A["ACC_Status_ACC"][2])
                mom = get_sig(d, A["ACC_Momentenanforderung"][0], A["ACC_Momentenanforderung"][1], False)
                verz = get_sig(d, A["ACC_Verz_anf"][0], A["ACC_Verz_anf"][1], True) * 0.005 - 7.22
                if c.src == 128:
                    st["stO"] = s; st["momO"] = mom; st["verzO"] = verz
                elif c.src == 2:
                    st["stS"] = s; st["momS"] = mom; st["verzS"] = verz
    if T0 <= f <= T1 and f % 5 == 0:
        print(f"{f:>6} {st['gas']:>3} {st['en']:>3} {st['v']*3.6:>4.0f} | {st['stO']:>3} {st['stS']:>3} | {st['momO']:>4.0f} {st['momS']:>4.0f} {st['verzO']:>6.2f} {st['verzS']:>6.2f} {st['at']:>5.2f} {st['a']:>5.2f}")
    st["f"] += 1
    if f > T1: break
del lr
