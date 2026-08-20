#!/usr/bin/env python3
"""00000039 anh=1 帧扫描：找所有 anh=1 时刻 + 上下文（vEgo/verz/st/src）
目标：确定原厂 ACC_Anhalten 的真实语义（停车发1？跟停瞬间？还是不用？）"""
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
A = {n: sig_def(n, 269) for n in ["ACC_Anhalten", "ACC_Verz_anf", "ACC_Status_ACC", "ACC_Momentenanforderung"]}
def get_sig(dat, start, length, signed):
    if len(dat) <= (start + length - 1) // 8: return 0
    val = 0
    for i in range(length):
        byte = (start + i) // 8
        bit = (start + i) % 8
        if dat[byte] & (1 << bit): val |= (1 << i)
    if signed and val & (1 << (length - 1)): val -= (1 << length)
    return val

segs = sorted(glob.glob("/data/media/0/realdata/00000039--*--rlog.zst"))
print(f"00000039 段数: {len(segs)}")

anh1_events = []
for si, p in enumerate(segs):
    try:
        lr = LogReader(p)
    except Exception:
        continue
    st = {"v": 0.0, "f": 0, "anhO": 0, "anhS": 0, "verzO": 99, "stO": -1}
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            st["v"] = msg.carState.vEgo
        elif msg.which() == "can":
            for cc in msg.can:
                if cc.address == 269 and cc.src in (128, 2):
                    d = bytes(cc.dat)
                    anh = get_sig(d, A["ACC_Anhalten"][0], A["ACC_Anhalten"][1], A["ACC_Anhalten"][2])
                    if anh:
                        if cc.src == 128:
                            st["anhO"] = 1
                            verz = get_sig(d, A["ACC_Verz_anf"][0], A["ACC_Verz_anf"][1], A["ACC_Verz_anf"][2]) * 0.005 - 7.22
                            s = get_sig(d, A["ACC_Status_ACC"][0], A["ACC_Status_ACC"][1], A["ACC_Status_ACC"][2])
                            anh1_events.append((si, f, "OP", st["v"], verz, s))
                        else:
                            st["anhS"] = 1
                            anh1_events.append((si, f, "原厂", st["v"], 99, -1))
        st["f"] += 1
    del lr
    if anh1_events and len(anh1_events) > 40:
        break

print(f"anh=1 帧总数: {len(anh1_events)}")
print("前 30 个 anh=1 帧（段/帧/来源/vEgo/verz/st）：")
for e in anh1_events[:30]:
    si, f, src, v, verz, s = e
    print(f"  段{si} 帧{f} [{src}] v={v*3.6:.0f}km/h verz={verz:.2f} st={s}")

if not anh1_events:
    print("（00000039 全段无 anh=1 帧——停车保持不用 anh，用 verz）")
