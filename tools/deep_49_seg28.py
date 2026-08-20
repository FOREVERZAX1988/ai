#!/usr/bin/env python3
"""00000049 段28 停车（284s，14次按键）深挖：按键时 OP/原厂反应 + 车动"""
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
A = {n: sig_def(n, 269) for n in ["ACC_Momentenanforderung", "ACC_Verz_anf", "ACC_Anhalten", "ACC_Status_ACC"]}
LS = {n: sig_def(n, 267) for n in ["LS_Tip_Setzen", "LS_Tip_Wiederaufnahme"]}
def get_sig(dat, start, length, signed):
    if len(dat) <= (start + length - 1) // 8: return 0
    val = 0
    for i in range(length):
        byte = (start + i) // 8
        bit = (start + i) % 8
        if dat[byte] & (1 << bit): val |= (1 << i)
    if signed and val & (1 << (length - 1)): val -= (1 << length)
    return val

segs = sorted(glob.glob("/data/media/0/realdata/00000049--*/rlog.zst"))
lr = LogReader(segs[28])
st = {"v":0.0,"en":False,"gas":False,"f":0,
      "anhO":-1,"momO":-99,"verzO":99,"stO":-1,
      "anhS":-1,"momS":0,"verzS":99,"stS":-1}
key_frames = []
moved_frame = None
print("=== 00000049 段28 停车(63626起, 284s) —— 按键/车动/信号 ===")
print(f"{'帧':>7} {'v':>4} {'gas':>3} {'按键':>4} | {'verzO':>6} {'momO':>5} {'stO':>3} | {'verzS':>6} {'momS':>5} {'stS':>3}")
for msg in lr:
    f = st["f"]
    if msg.which() == "carState":
        cs = msg.carState
        st["v"] = cs.vEgo; st["en"] = cs.cruiseState.enabled; st["gas"] = cs.gasPressed
        if moved_frame is None and f > 63626 + 100 and st["v"] > 0.5:
            moved_frame = f
    elif msg.which() == "can":
        for cc in msg.can:
            if cc.address == 269 and cc.src in (128, 2):
                d = bytes(cc.dat)
                anh = get_sig(d, A["ACC_Anhalten"][0], A["ACC_Anhalten"][1], A["ACC_Anhalten"][2])
                mom = get_sig(d, A["ACC_Momentenanforderung"][0], A["ACC_Momentenanforderung"][1], A["ACC_Momentenanforderung"][2])
                verz = get_sig(d, A["ACC_Verz_anf"][0], A["ACC_Verz_anf"][1], A["ACC_Verz_anf"][2]) * 0.005 - 7.22
                s = get_sig(d, A["ACC_Status_ACC"][0], A["ACC_Status_ACC"][1], A["ACC_Status_ACC"][2])
                if cc.src == 128:
                    st["anhO"]=anh; st["momO"]=mom; st["verzO"]=verz; st["stO"]=s
                else:
                    st["anhS"]=anh; st["momS"]=mom; st["verzS"]=verz; st["stS"]=s
            elif cc.address == 267 and cc.src == 0 and len(cc.dat) >= 4:
                d = bytes(cc.dat)
                stz = get_sig(d, LS["LS_Tip_Setzen"][0], LS["LS_Tip_Setzen"][1], LS["LS_Tip_Setzen"][2])
                rsm = get_sig(d, LS["LS_Tip_Wiederaufnahme"][0], LS["LS_Tip_Wiederaufnahme"][1], LS["LS_Tip_Wiederaufnahme"][2])
                if stz or rsm:
                    key_frames.append(f)
    if f % 200 == 0 and 63600 <= f <= 63626 + 28400 + 500:
        kf = sum(1 for k in key_frames if k >= f-200 and k <= f)
        print(f"{f:>7} {st['v']*3.6:>4.0f} {int(st['gas']):>3} {kf:>4} | {st['verzO']:>6.2f} {st['momO']:>5.0f} {st['stO']:>3} | {st['verzS']:>6.2f} {st['momS']:>5.0f} {st['stS']:>3}")
    st["f"] += 1
    if f > 63626 + 30000: break
del lr
print(f"\n按键总次数: {len(key_frames)} 帧 {key_frames[:10]}")
print(f"车动帧: {moved_frame}  (停车开始 63626)")

# 车动时刻上下文（若存在）
if moved_frame:
    lr = LogReader(segs[28])
    st = {"v":0.0,"gas":False,"f":0,"verzO":99,"momO":0,"stO":-1}
    print(f"\n=== 车动@{moved_frame} 前3秒到后0.5秒（每30帧）===")
    print(f"{'帧':>7} {'v':>4} {'gas':>3} | {'verzO':>6} {'momO':>5} {'stO':>3}")
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            cs = msg.carState
            st["v"] = cs.vEgo; st["gas"] = cs.gasPressed
        elif msg.which() == "can":
            for cc in msg.can:
                if cc.address == 269 and cc.src == 128:
                    d = bytes(cc.dat)
                    st["verzO"] = get_sig(d, A["ACC_Verz_anf"][0], A["ACC_Verz_anf"][1], A["ACC_Verz_anf"][2]) * 0.005 - 7.22
                    st["momO"] = get_sig(d, A["ACC_Momentenanforderung"][0], A["ACC_Momentenanforderung"][1], A["ACC_Momentenanforderung"][2])
                    st["stO"] = get_sig(d, A["ACC_Status_ACC"][0], A["ACC_Status_ACC"][1], A["ACC_Status_ACC"][2])
        if moved_frame - 300 <= f <= moved_frame + 50 and f % 30 == 0:
            print(f"{f:>7} {st['v']*3.6:>4.0f} {int(st['gas']):>3} | {st['verzO']:>6.2f} {st['momO']:>5.0f} {st['stO']:>3}")
        st["f"] += 1
    del lr
