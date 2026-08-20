#!/usr/bin/env python3
"""00000049（原厂ACC，官方master）停车→起步行为分析
目标：①确认原厂纵向无OP代发 ②原厂停车时 anhS 状态 ③原厂起步序列（anh/verz/mom）"""
import glob, sys, re
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
from collections import Counter

DBC = "opendbc_repo/opendbc/dbc/vw_mlb.dbc"
dbc_text = open(DBC, encoding="latin-1").read()

def sig_def(name, msg_id):
    m = re.search(rf'^ SG_ {name} : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)', dbc_text, re.M)
    if not m:
        return None
    start, length, signed = int(m.group(1)), int(m.group(2)), m.group(4) == '-'
    scale, offset = float(m.group(5)), float(m.group(6))
    lines = dbc_text.splitlines()
    for i, ln in enumerate(lines):
        if f'SG_ {name} ' in ln:
            for j in range(i, -1, -1):
                bm = re.match(r'^BO_ (\d+) (\w+)', lines[j])
                if bm and int(bm.group(1)) == msg_id:
                    return start, length, signed, scale, offset
    return None

A = {n: sig_def(n, 269) for n in ["ACC_Momentenanforderung", "ACC_Verz_anf", "ACC_Anhalten", "ACC_Status_ACC"]}
LS = {n: sig_def(n, 267) for n in ["LS_Tip_Setzen", "LS_Tip_Wiederaufnahme"]}

def get_sig(dat, start, length, signed):
    if len(dat) <= (start + length - 1) // 8:
        return 0
    val = 0
    for i in range(length):
        byte = (start + i) // 8
        bit = (start + i) % 8
        if dat[byte] & (1 << bit):
            val |= (1 << i)
    if signed and val & (1 << (length - 1)):
        val -= (1 << length)
    return val

segs = sorted(glob.glob("/data/media/0/realdata/00000002--*--rlog.zst"))[:25]
print(f"00000002(前25段) 段数: {len(segs)}")

# ========== ① 269 src 分布（确认纯原厂纵向）==========
lr = LogReader(segs[3])
c = Counter()
n = 0
for msg in lr:
    if msg.which() == "can":
        for cc in msg.can:
            if cc.address == 269:
                c[cc.src] += 1
    n += 1
    if n > 30000:
        break
del lr
print(f"段3 269(ACC_05) src 分布: {dict(c)}")

# ========== ② 停车事件：原厂 anhS 状态 + 车动 ==========
print("\n=== 停车事件（enabled 且 v<0.1 持续≥5s）===")
print(f"{'段':>3} {'起始帧':>7} {'时长s':>5} {'anhS=1帧':>8} {'anhS=0帧':>8} {'按键':>4} {'车动?':>5}")
events = []
for si in range(len(segs)):
    try:
        lr = LogReader(segs[si])
    except Exception:
        continue
    st = {"v": 0.0, "en": False, "f": 0, "anhS": 0}
    stop_start = None
    a1 = a0 = keys = 0
    moved = False
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            cs = msg.carState
            st["v"] = cs.vEgo
            st["en"] = cs.cruiseState.enabled
        elif msg.which() == "can":
            for cc in msg.can:
                if cc.address == 269 and cc.src == 2:
                    d = bytes(cc.dat)
                    st["anhS"] = get_sig(d, A["ACC_Anhalten"][0], A["ACC_Anhalten"][1], A["ACC_Anhalten"][2])
                elif cc.address == 267 and cc.src == 0 and len(cc.dat) >= 4:
                    d = bytes(cc.dat)
                    stz = get_sig(d, LS["LS_Tip_Setzen"][0], LS["LS_Tip_Setzen"][1], LS["LS_Tip_Setzen"][2])
                    rsm = get_sig(d, LS["LS_Tip_Wiederaufnahme"][0], LS["LS_Tip_Wiederaufnahme"][1], LS["LS_Tip_Wiederaufnahme"][2])
                    if stz or rsm:
                        keys += 1
        if st["en"] and st["v"] < 0.1:
            if stop_start is None:
                stop_start = f
            if st["anhS"] == 1:
                a1 += 1
            else:
                a0 += 1
        else:
            if stop_start is not None:
                dur = f - stop_start
                if dur >= 500:
                    moved = st["v"] > 0.5
                    events.append((si, stop_start, dur, a1, a0, keys, moved))
                    print(f"{si:>3} {stop_start:>7} {dur/100:>5.0f} {a1:>8} {a0:>8} {keys:>4} {moved!s:>5}")
                stop_start = None
                a1 = a0 = keys = 0
        st["f"] += 1
    del lr
print(f"共 {len(events)} 个停车事件")

# ========== ③ 深挖第一个"车动"事件（原厂起步序列）==========
moved_ev = [e for e in events if e[6]]
if moved_ev:
    si, s0, dur, a1, a0, keys, _ = moved_ev[0]
    print(f"\n=== 原厂自动起步序列（段{si} 停车@{s0} 时长{dur/100:.0f}s，按键{keys}次）===")
    lr = LogReader(segs[si])
    st = {"v": 0.0, "f": 0, "anhS": -1, "verzS": 99, "momS": 0, "stS": -1, "lead_v": 0.0}
    print(f"{'帧':>7} {'vEgo':>5} {'anhS':>4} {'verzS':>6} {'momS':>5} {'stS':>3} {'leadV':>6}")
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            st["v"] = msg.carState.vEgo
        elif msg.which() == "modelV2":
            if len(msg.modelV2.leadsV3) > 0:
                st["lead_v"] = msg.modelV2.leadsV3[0].v[0]
        elif msg.which() == "can":
            for cc in msg.can:
                if cc.address == 269 and cc.src == 2:
                    d = bytes(cc.dat)
                    st["anhS"] = get_sig(d, A["ACC_Anhalten"][0], A["ACC_Anhalten"][1], A["ACC_Anhalten"][2])
                    st["verzS"] = get_sig(d, A["ACC_Verz_anf"][0], A["ACC_Verz_anf"][1], A["ACC_Verz_anf"][2]) * 0.005 - 7.22
                    st["momS"] = get_sig(d, A["ACC_Momentenanforderung"][0], A["ACC_Momentenanforderung"][1], A["ACC_Momentenanforderung"][2])
                    st["stS"] = get_sig(d, A["ACC_Status_ACC"][0], A["ACC_Status_ACC"][1], A["ACC_Status_ACC"][2])
        if s0 <= f <= s0 + dur and f % 200 == 0:
            print(f"{f:>7} {st['v']*3.6:>5.0f} {st['anhS']:>4} {st['verzS']:>6.2f} {st['momS']:>5} {st['stS']:>3} {st['lead_v']:>6.1f}")
        st["f"] += 1
    del lr
else:
    print("\n无车动事件（原厂停车后都没自动起步？——需要进一步确认）")
