#!/usr/bin/env python3
"""深挖 v3（修正版）：0000004f
① 267(LS_01) 按键事件：src=0/1/130（用户物理按键在 bus0）
② 段7 开头 TSK_Status 轨迹（原厂 ACC 状态机，查 mismatch/退出）
③ gasPressed 统计与退出事件"""
import glob, sys, re
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
from collections import Counter

DBC = "opendbc_repo/opendbc/dbc/vw_mlb.dbc"
dbc_text = open(DBC, encoding="latin-1").read()

def sig_def(name, msg_id=None):
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
                if bm:
                    bid = int(bm.group(1))
                    if msg_id is None or bid == msg_id:
                        return bid, start, length, signed, scale, offset
                    else:
                        break
    return None

LS = {n: sig_def(n, 267) for n in ["LS_Tip_Setzen", "LS_Tip_Wiederaufnahme", "LS_Hauptschalter"]}
A = {n: sig_def(n, 269) for n in ["ACC_Momentenanforderung", "ACC_Verz_anf", "ACC_Anhalten", "ACC_Status_ACC"]}
TSK = sig_def("TSK_Status")  # 任意报文（扫所有）
TSK_ACC1 = sig_def("TSK_Status_GRA_ACC_01")  # BO_ 268? 或 265
TSK_ACC2 = sig_def("TSK_Status_GRA_ACC_02")
print("TSK_Status:", TSK[:2] if TSK else None, "| GRA_ACC_01:", TSK_ACC1[:2] if TSK_ACC1 else None, "| GRA_ACC_02:", TSK_ACC2[:2] if TSK_ACC2 else None)

def get_sig(dat, start, length, signed):
    val = 0
    if len(dat) <= (start + length - 1) // 8:
        return 0
    for i in range(length):
        byte = (start + i) // 8
        bit = (start + i) % 8
        if dat[byte] & (1 << bit):
            val |= (1 << i)
    if signed and val & (1 << (length - 1)):
        val -= (1 << length)
    return val

segs = sorted(glob.glob("/data/media/0/realdata/0000004f--*/rlog.zst"))

# ========== ① 按键事件（src=0/1/130，用户物理按键）==========
print("="*60)
print("① 用户按键事件（267 src=0/1/130）全段")
print("="*60)
for si in [1, 3, 7, 9, 11]:
    lr = LogReader(segs[si])
    st = {"f": 0, "v": 0}
    keys = []
    for msg in lr:
        if msg.which() == "carState":
            st["v"] = msg.carState.vEgo
        elif msg.which() == "can":
            for c in msg.can:
                if c.address == 267 and c.src in (0, 1):
                    d = bytes(c.dat)
                    stz = get_sig(d, LS["LS_Tip_Setzen"][0], LS["LS_Tip_Setzen"][1], LS["LS_Tip_Setzen"][2])
                    rsm = get_sig(d, LS["LS_Tip_Wiederaufnahme"][0], LS["LS_Tip_Wiederaufnahme"][1], LS["LS_Tip_Wiederaufnahme"][2])
                    if stz or rsm:
                        keys.append((st["f"], "SET" if stz else "RESUME", f"v={st['v']*3.6:.0f}"))
        st["f"] += 1
        if st["f"] > 65000:
            break
    del lr
    print(f"段{si}: 按键 {len(keys)} 次 -> " + "; ".join(f"帧{f}{k}({v})" for f, k, v in keys[:8]))

# ========== ② 段7 开头 TSK/ACC 状态轨迹（第二段点火/切开关）==========
print("\n" + "="*60)
print("② 段7 开头 3000 帧：原厂状态轨迹（找 mismatch/退出）")
print("="*60)
lr = LogReader(segs[7])
st = {"f": 0, "tsk": -1, "stS": -1, "anhS": -1, "en": 0}
last_tsk = None; last_st = None
for msg in lr:
    if msg.which() == "carState":
        st["en"] = msg.carState.cruiseState.enabled
    elif msg.which() == "can":
        for c in msg.can:
            if c.address == 269 and c.src == 2:
                d = bytes(c.dat)
                st["stS"] = get_sig(d, A["ACC_Status_ACC"][0], A["ACC_Status_ACC"][1], A["ACC_Status_ACC"][2])
                st["anhS"] = get_sig(d, A["ACC_Anhalten"][0], A["ACC_Anhalten"][1], A["ACC_Anhalten"][2])
            elif TSK and c.address == TSK[0] and c.src == 2:
                d = bytes(c.dat)
                st["tsk"] = get_sig(d, TSK[1], TSK[2], TSK[3])
    f = st["f"]
    if f % 500 == 0 and f <= 3000:
        print(f"帧{f}: en={st['en']} stS={st['stS']} anhS={st['anhS']} tsk={st['tsk']}")
    st["f"] += 1
    if f > 3000:
        break
del lr

# ========== ③ gasPressed 统计与退出 ==========
print("\n" + "="*60)
print("③ gasPressed 统计（段8-14）+ 1→0 后 enabled")
print("="*60)
for si in range(8, 15):
    lr = LogReader(segs[si])
    st = {"gas": 0, "en": 0, "f": 0, "pg": 0, "pe": 0, "gas_n": 0}
    exits = []
    for msg in lr:
        if msg.which() == "carState":
            cs = msg.carState
            st["gas"] = cs.gasPressed
            st["en"] = cs.cruiseState.enabled
        f = st["f"]
        if st["gas"]:
            st["gas_n"] += 1
        if st["pg"] == 1 and st["gas"] == 0 and st["pe"] and f > 100:
            # 松开油门后 0.5s 采样 enabled
            exits.append((f, st["en"]))
        st["pg"] = st["gas"]; st["pe"] = st["en"]
        st["f"] += 1
        if f > 60000:
            break
    del lr
    lost = [f for f, e in exits if not e]
    print(f"段{si}: gas帧={st['gas_n']} 松开油门事件={len(exits)} 松开后enabled退出={len(lost)}" + (f" 退出帧: {lost[:4]}" if lost else ""))
