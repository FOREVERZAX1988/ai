#!/usr/bin/env python3
"""深挖第一个踩油门退出事件（段0帧96779）：踩油门前后3秒完整信号轨迹
stO(OP代发)/stS(原厂)/momO/momS/aTarget/accel——找 stO 跳 0 的确切时机和原因"""
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

segs = sorted(glob.glob("/data/media/0/realdata/0000004f--*/rlog.zst"))
lr = LogReader(segs[0])
st = {"f": 0, "gas": 0, "en": 0, "at": 0.0, "accel": 0.0,
      "stO": -1, "stS": -1, "momO": 0, "momS": 0, "verzO": 99}
T0, T1 = 96600, 97200  # 事件1 踩油门96779 松开96889
print(f"事件1 深挖（段0 帧{T0}-{T1}，每10帧）：gas/en/stO/stS/momO/momS/aTarget")
print(f"{'帧':>6} {'gas':>3} {'en':>3} | {'stO':>3} {'stS':>3} | {'momO':>4} {'momS':>4} {'verzO':>6} {'aTgt':>5} {'accel':>5}")
for msg in lr:
    f = st["f"]
    if msg.which() == "carState":
        cs = msg.carState
        st["gas"] = cs.gasPressed
        st["en"] = cs.cruiseState.enabled
        st["accel"] = cs.aEgo
    elif msg.which() == "longitudinalPlan":
        st["at"] = msg.longitudinalPlan.aTarget
    elif msg.which() == "can":
        for c in msg.can:
            if c.address == 269 and len(c.dat) >= 8:
                d = bytes(c.dat)
                s = get_sig(d, A["ACC_Status_ACC"][0], A["ACC_Status_ACC"][1], A["ACC_Status_ACC"][2])
                mom = get_sig(d, A["ACC_Momentenanforderung"][0], A["ACC_Momentenanforderung"][1], False)
                if c.src == 128:
                    st["stO"] = s; st["momO"] = mom
                    st["verzO"] = get_sig(d, A["ACC_Verz_anf"][0], A["ACC_Verz_anf"][1], True) * 0.005 - 7.22
                elif c.src == 2:
                    st["stS"] = s; st["momS"] = mom
    if T0 <= f <= T1 and f % 10 == 0:
        print(f"{f:>6} {st['gas']:>3} {st['en']:>3} | {st['stO']:>3} {st['stS']:>3} | {st['momO']:>4.0f} {st['momS']:>4.0f} {st['verzO']:>6.2f} {st['at']:>5.2f} {st['accel']:>5.2f}")
    st["f"] += 1
    if f > T1: break
del lr
