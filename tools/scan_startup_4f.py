#!/usr/bin/env python3
"""4f 全部"停车中按SET"事件：车动 vs 没动 的 Loeseanf/verz/mom/st 对比
目标：验证"车动 ⇔ Loeseanforderung=1"（用户提出的核对思路）"""
import glob, sys, re
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

DBC = "opendbc_repo/opendbc/dbc/vw_mlb.dbc"
dbc_text = open(DBC, encoding="latin-1").read()
def sig_def(name, msg_id):
    m = re.search(rf'^ SG_ {name} : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)', dbc_text, re.M)
    if not m: return None
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
A = {n: sig_def(n, 269) for n in ["ACC_Loeseanforderung", "ACC_Verz_anf", "ACC_Momentenanforderung", "ACC_Status_ACC"]}
LS = {n: sig_def(n, 267) for n in ["LS_Tip_Setzen"]}
print("defs:", {k: v[:2] for k, v in A.items()}, {k: v[:2] for k, v in LS.items()})

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

segs = sorted(glob.glob("/data/media/0/realdata/0000004f--*/rlog.zst"))
print(f"\n{'段':>3} {'停车帧':>7} {'按键帧':>7} {'车动帧':>7} {'结果':>8} | {'原厂Loe':>6} {'verzS':>6} {'momS':>5} {'stS':>3} | {'OP Loe':>5} {'verzO':>6} {'momO':>5} {'stO':>3}")

for si, p in enumerate(segs):
    try:
        lr = LogReader(p)
    except Exception:
        continue
    st = {"v": 0.0, "en": False, "f": 0,
          "loesS": 0, "verzS": 99, "momS": -99, "stS": -1,
          "loesO": 0, "verzO": 99, "momO": -99, "stO": -1,
          "key_frame": None, "stop_start": None}
    keyed = False
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            cs = msg.carState
            st["v"] = cs.vEgo
            st["en"] = cs.cruiseState.enabled
        elif msg.which() == "can":
            for c in msg.can:
                if c.address == 269 and len(c.dat) >= 8:
                    d = bytes(c.dat)
                    loes = get_sig(d, A["ACC_Loeseanforderung"][0], A["ACC_Loeseanforderung"][1], A["ACC_Loeseanforderung"][2])
                    verz = get_sig(d, A["ACC_Verz_anf"][0], A["ACC_Verz_anf"][1], A["ACC_Verz_anf"][2]) * 0.005 - 7.22
                    mom = get_sig(d, A["ACC_Momentenanforderung"][0], A["ACC_Momentenanforderung"][1], A["ACC_Momentenanforderung"][2])
                    s = get_sig(d, A["ACC_Status_ACC"][0], A["ACC_Status_ACC"][1], A["ACC_Status_ACC"][2])
                    if c.src == 2:
                        st["loesS"] = loes; st["verzS"] = verz; st["momS"] = mom; st["stS"] = s
                    elif c.src == 128:
                        st["loesO"] = loes; st["verzO"] = verz; st["momO"] = mom; st["stO"] = s
                elif c.address == 267 and c.src == 0 and len(c.dat) >= 4:
                    d = bytes(c.dat)
                    stz = get_sig(d, LS["LS_Tip_Setzen"][0], LS["LS_Tip_Setzen"][1], LS["LS_Tip_Setzen"][2])
                    if stz and st["en"] and st["v"] < 0.1 and st["key_frame"] is None:
                        st["key_frame"] = f
                        st["stop_start"] = st["stop_start"] if st["stop_start"] is not None else f
                        keyed = True
        # 停车窗口检测：v<0.1 & enabled
        if st["en"] and st["v"] < 0.1:
            if st["stop_start"] is None:
                st["stop_start"] = f
        else:
            st["stop_start"] = None
        # 车动检测（按键后10秒内）
        if keyed and st["key_frame"] is not None and f > st["key_frame"] and st["v"] > 0.5:
            dur_stop = (st["key_frame"] - st["stop_start"]) if st["stop_start"] else 0
            print(f"{si:>3} {st['stop_start'] if st['stop_start'] else '?':>7} {st['key_frame']:>7} {f:>7} {'✅车动':>8} | "
                  f"{st['loesS']:>6} {st['verzS']:>6.2f} {st['momS']:>5.0f} {st['stS']:>3} | "
                  f"{st['loesO']:>5} {st['verzO']:>6.2f} {st['momO']:>5.0f} {st['stO']:>3}")
            keyed = False
            st["key_frame"] = None
        # 按键后3秒内输出采样（未车动情况）
        if keyed and st["key_frame"] is not None and f - st["key_frame"] == 300 and st["v"] < 0.1:
            print(f"{si:>3} {st['stop_start'] if st['stop_start'] else '?':>7} {st['key_frame']:>7} {'—':>7} {'❌没动':>8} | "
                  f"{st['loesS']:>6} {st['verzS']:>6.2f} {st['momS']:>5.0f} {st['stS']:>3} | "
                  f"{st['loesO']:>5} {st['verzO']:>6.2f} {st['momO']:>5.0f} {st['stO']:>3}")
            keyed = False
            st["key_frame"] = None
        st["f"] += 1
    del lr
