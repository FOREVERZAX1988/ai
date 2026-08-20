#!/usr/bin/env python3
"""补深挖 4e 段2 stO 跳 0 瞬间（34380-34410）：打 available/accFaulted/longActive
判断 acc_control_value 的哪个条件让 stO=0（long_active 掉 / main_switch_on 掉 / acc_faulted）"""
import glob, sys, re
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

DBC = "opendbc_repo/opendbc/dbc/vw_mlb.dbc"
dbc_text = open(DBC, encoding="latin-1").read()
def sig_def(name, msg_id):
    m = re.search(rf'^ SG_ {name} : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)', dbc_text, re.M)
    if not m: return None
    return (int(m.group(1)), int(m.group(2)), m.group(4)=='-', float(m.group(5)), float(m.group(6)))
ST = sig_def("ACC_Status_ACC", 269)
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
st = {"f": 0, "gas": 0, "en": 0, "avail": 0, "fault": 0, "lactive": 0, "stO": -1, "stS": -1}
print(f"{'帧':>6} {'gas':>3} {'en':>3} {'avail':>5} {'fault':>5} {'longActive':>9} | {'stO':>3} {'stS':>3}")
for msg in lr:
    f = st["f"]
    if msg.which() == "carState":
        cs = msg.carState
        st["gas"] = cs.gasPressed
        st["en"] = cs.cruiseState.enabled
        st["avail"] = cs.cruiseState.available
        st["fault"] = cs.accFaulted
    elif msg.which() == "carControl":
        st["lactive"] = msg.carControl.longActive
    elif msg.which() == "can":
        for c in msg.can:
            if c.address == 269 and len(c.dat) >= 8:
                d = bytes(c.dat)
                s = get_sig(d, ST[0], ST[1], ST[2])
                if c.src == 128:
                    st["stO"] = s
                elif c.src == 2:
                    st["stS"] = s
    if 34370 <= f <= 34430 and f % 2 == 0:
        print(f"{f:>6} {st['gas']:>3} {st['en']:>3} {st['avail']:>5} {st['fault']:>5} {st['lactive']:>9} | {st['stO']:>3} {st['stS']:>3}")
    st["f"] += 1
    if f > 34430: break
del lr
