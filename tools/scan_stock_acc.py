#!/usr/bin/env python3
"""找"纯原厂ACC"时段：OP未激活（en=False）但原厂ACC在控制（src=2 status=3）
然后计算这些时段的：实际jerk（ESP微分）+ 加速度幅度，对比OP激活时段
route格式：00000002/04/4d 扁平（--N--rlog.zst）；00000049/4f 目录（--N/rlog.zst）"""
import glob, sys, re
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

DBC = "opendbc_repo/opendbc/dbc/vw_mlb.dbc"
dbc_text = open(DBC, encoding="latin-1").read()
def sig_def(name, msg_id):
    m = re.search(rf'^ SG_ {name} : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)', dbc_text, re.M)
    if not m: return None
    return (int(m.group(1)), int(m.group(2)), m.group(4)=='-', float(m.group(5)), float(m.group(6)))
ESPL = sig_def("ESP_Laengsbeschl", 257)
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

routes = [
    ("00000002", "早期SP_MACAN_LONG_RE", "flat"),
    ("00000004", "早期(力矩基线)", "flat"),
    ("00000049", "官方master(用户补传)", "dir"),
    ("0000004d", "macan-long-0816", "flat"),
    ("0000004f", "macan-long-0820(8.20路试)", "dir"),
]

for route, label, fmt in routes:
    if fmt == "flat":
        segs = sorted(glob.glob(f"/data/media/0/realdata/{route}--*--rlog.zst"))
    else:
        segs = sorted(glob.glob(f"/data/media/0/realdata/{route}--*/rlog.zst"))
    stock_frames = 0
    op_frames = 0
    for p in segs[:5]:
        try:
            lr = LogReader(p)
        except Exception:
            continue
        st = {"f": 0, "en": False, "stS": -1, "espl": 0.0, "espl_hist": []}
        for msg in lr:
            f = st["f"]
            if msg.which() == "carState":
                st["en"] = msg.carState.cruiseState.enabled
            elif msg.which() == "can":
                for c in msg.can:
                    if c.address == 269 and c.src == 2 and len(c.dat) >= 8:
                        d = bytes(c.dat)
                        st["stS"] = get_sig(d, ST[0], ST[1], ST[2])
                    elif c.address == 257 and len(c.dat) >= 6:
                        d = bytes(c.dat)
                        st["espl"] = get_sig(d, ESPL[0], ESPL[1], ESPL[2]) * ESPL[3] + ESPL[4]
                        st["espl_hist"].append((f, st["espl"]))
                        if len(st["espl_hist"]) > 200: st["espl_hist"].pop(0)
            if not st["en"] and st["stS"] == 3:
                stock_frames += 1
            elif st["en"]:
                op_frames += 1
            st["f"] += 1
            if st["f"] > 40000: break
        del lr
        if stock_frames > 8000:
            break
    print(f"{route} ({label}): 纯原厂ACC激活帧={stock_frames} | OP激活帧={op_frames} | 段数扫={min(len(segs),20)}")
