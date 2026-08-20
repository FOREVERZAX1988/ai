#!/usr/bin/env python3
"""实测 4e 段2 踩油门事件窗口（34360-34600）：
①我们代发的 anhO（src=128 ACC_Anhalten 56|1）——用户问"修复成0"验证
②原厂帧 anhS（src=2 ACC_Anhalten）
③LoC 输出 actuators.accel（carControl）
④longControlState（rlog 如有）
⑤aTarget（planner）/momO/momS"""
import glob, sys, re
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

DBC = "opendbc_repo/opendbc/dbc/vw_mlb.dbc"
dbc_text = open(DBC, encoding="latin-1").read()
def sig_def(name, msg_id):
    m = re.search(rf'^ SG_ {name} : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)', dbc_text, re.M)
    if not m: return None
    return (int(m.group(1)), int(m.group(2)), m.group(4)=='-', float(m.group(5)), float(m.group(6)))
ANH = sig_def("ACC_Anhalten", 269)
MOM = sig_def("ACC_Momentenanforderung", 269)
print("ACC_Anhalten@269:", ANH[:3] if ANH else None, "| ACC_Momentenanforderung:", MOM[:2] if MOM else None)

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
st = {"f": 0, "gas": 0, "en": 0, "v": 0.0, "at": 0.0, "accel": 99.0,
      "anhO": -1, "anhS": -1, "momO": 0, "momS": 0, "lcs": -1}
print(f"{'帧':>6} {'gas':>3} {'en':>3} {'v':>3} | {'aTgt':>5} {'accel':>5} | {'anhO(我们)':>8} {'anhS(原厂)':>8} {'momO':>4} {'momS':>4} {'LCS':>4}")
for msg in lr:
    f = st["f"]
    if msg.which() == "carState":
        cs = msg.carState
        st["gas"] = cs.gasPressed
        st["en"] = cs.cruiseState.enabled
        st["v"] = cs.vEgo
    elif msg.which() == "longitudinalPlan":
        st["at"] = msg.longitudinalPlan.aTarget
    elif msg.which() == "carControl":
        st["accel"] = msg.carControl.actuators.accel
    elif msg.which() == "controlsState":
        st["lcs"] = msg.controlsState.longControlState
    elif msg.which() == "can":
        for c in msg.can:
            if c.address == 269 and len(c.dat) >= 8:
                d = bytes(c.dat)
                anh = get_sig(d, ANH[0], ANH[1], ANH[2])
                mom = get_sig(d, MOM[0], MOM[1], False)
                if c.src == 128:
                    st["anhO"] = anh; st["momO"] = mom
                elif c.src == 2:
                    st["anhS"] = anh; st["momS"] = mom
    if 34360 <= f <= 34600 and f % 10 == 0:
        print(f"{f:>6} {st['gas']:>3} {st['en']:>3} {st['v']*3.6:>3.0f} | {st['at']:>5.2f} {st['accel']:>5.2f} | {st['anhO']:>8} {st['anhS']:>8} {st['momO']:>4.0f} {st['momS']:>4.0f} {str(st['lcs']):>18}")
    st["f"] += 1
    if f > 34600: break
del lr
