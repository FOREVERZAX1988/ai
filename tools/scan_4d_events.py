#!/usr/bin/env python3
"""4d（0816老分支）踩油门→原厂退出事件扫描 + 第一个事件窗口深挖
①扫全部段：gas时段内 原厂 stS(57|3) 从 3/4 变 0/6 → 退出事件
②深挖第一个事件：LCS/accel/momO/momS/anhO/anhS/aTgt/v——确认是否同"LoC卡stopping"模式"""
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
def st57(d):
    return (d[7] >> 1) & 0x7  # ACC_Status_ACC @57|3（修正）
def get_sig(dat, start, length, signed):
    if len(dat) <= (start + length - 1) // 8: return 0
    val = 0
    for i in range(length):
        byte = (start + i) // 8
        bit = (start + i) % 8
        if dat[byte] & (1 << bit): val |= (1 << i)
    if signed and val & (1 << (length - 1)): val -= (1 << length)
    return val

segs = sorted(glob.glob("/data/media/0/realdata/0000004d--*--rlog.zst"))
print(f"4d 段数: {len(segs)}")

# ========== ① 事件扫描 ==========
events = []
for si in range(len(segs)):
    try:
        lr = LogReader(segs[si])
    except Exception:
        continue
    st = {"f": 0, "gas": 0, "pg": 0, "stS": -1, "pstS": -1}
    gas_start = None
    in_gas = False
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            st["gas"] = msg.carState.gasPressed
        elif msg.which() == "can":
            for c in msg.can:
                if c.address == 269 and c.src == 2 and len(c.dat) >= 8:
                    st["stS"] = st57(bytes(c.dat))
        if st["gas"] and not in_gas:
            gas_start = f
            in_gas = True
        if in_gas and st["pstS"] in (3, 4) and st["stS"] in (0, 6) and f > gas_start + 5:
            events.append((si, gas_start, f))
            in_gas = False
            gas_start = None
        if in_gas and st["pg"] == 1 and st["gas"] == 0:
            in_gas = False
            gas_start = None
        st["pg"] = st["gas"]; st["pstS"] = st["stS"]
        st["f"] += 1
    del lr
print(f"4d 踩油门→原厂退出事件: {len(events)} 个")
for e in events[:10]:
    print(f"  段{e[0]} 踩油门@{e[1]} 退出@{e[2]} 时长{(e[2]-e[1])/100:.2f}s")

# ========== ② 深挖第一个事件 ==========
if events:
    si, g0, g1 = events[0]
    T0, T1 = g0 - 50, g1 + 100
    print(f"\n===== 深挖 4d 段{si} 事件（踩油门@{g0} 退出@{g1}）=====")
    lr = LogReader(segs[si])
    st = {"f": 0, "gas": 0, "en": 0, "v": 0.0, "at": 0.0, "accel": 99.0,
          "anhO": -1, "anhS": -1, "momO": 0, "momS": 0, "lcs": -1}
    print(f"{'帧':>6} {'gas':>3} {'en':>3} {'v':>3} | {'aTgt':>5} {'accel':>5} | {'anhO':>4} {'anhS':>4} {'momO':>4} {'momS':>4} {'LCS':>18}")
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            cs = msg.carState
            st["gas"] = cs.gasPressed; st["en"] = cs.cruiseState.enabled; st["v"] = cs.vEgo
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
        if T0 <= f <= T1 and f % 10 == 0:
            print(f"{f:>6} {st['gas']:>3} {st['en']:>3} {st['v']*3.6:>3.0f} | {st['at']:>5.2f} {st['accel']:>5.2f} | {st['anhO']:>4} {st['anhS']:>4} {st['momO']:>4.0f} {st['momS']:>4.0f} {str(st['lcs']):>18}")
        st["f"] += 1
        if f > T1: break
    del lr
