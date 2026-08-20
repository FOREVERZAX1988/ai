#!/usr/bin/env python3
"""0000004f 全段：用户物理按键(src=0) vs OP转发(src=1/130) —— 转发完整性验证
可靠逻辑（v4 同款）：len(dat)>=4 保护 + src 区分"""
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
LS = {n: sig_def(n, 267) for n in ["LS_Tip_Setzen", "LS_Tip_Wiederaufnahme"]}
print("LS defs:", {k: v[:2] for k, v in LS.items()})

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
print(f"0000004f 段数: {len(segs)}")
print(f"\n{'段':>3} {'用户SET':>6} {'用户RESUME':>8} {'转发SET':>7} {'转发RESUME':>9}  用户按键帧(前8)")
for si, p in enumerate(segs):
    try:
        lr = LogReader(p)
    except Exception:
        continue
    u_set = u_rsm = f_set = f_rsm = 0
    key_frames = []
    st = {"f": 0}
    for msg in lr:
        f = st["f"]
        if msg.which() == "can":
            for c in msg.can:
                if c.address == 267 and len(c.dat) >= 4:
                    d = bytes(c.dat)
                    stz = get_sig(d, LS["LS_Tip_Setzen"][0], LS["LS_Tip_Setzen"][1], LS["LS_Tip_Setzen"][2])
                    rsm = get_sig(d, LS["LS_Tip_Wiederaufnahme"][0], LS["LS_Tip_Wiederaufnahme"][1], LS["LS_Tip_Wiederaufnahme"][2])
                    if stz or rsm:
                        if c.src == 0:
                            if stz: u_set += 1
                            if rsm: u_rsm += 1
                            key_frames.append(f)
                        elif c.src in (1, 130):
                            if stz: f_set += 1
                            if rsm: f_rsm += 1
        st["f"] += 1
    del lr
    kf = ",".join(str(x) for x in key_frames[:8])
    print(f"{si:>3} {u_set:>6} {u_rsm:>8} {f_set:>7} {f_rsm:>9}  [{kf}]")
