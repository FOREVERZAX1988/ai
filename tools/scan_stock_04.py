#!/usr/bin/env python3
"""确认 00000002/00000004 是否有"原厂 ACC 自己控制"的时段：
OP 未 engage（en=False）但原厂在控制（src=2 的 269 帧 verz/mom 非零、vEgo 在跑）
每段一行：v范围 / en帧数 / 原厂stS分布 / 原厂mom均值 / OP代发(128)帧数"""
import glob, sys, re
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
from collections import Counter

DBC = "opendbc_repo/opendbc/dbc/vw_mlb.dbc"
dbc_text = open(DBC, encoding="latin-1").read()
def sig_def(name, msg_id):
    m = re.search(rf'^ SG_ {name} : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)', dbc_text, re.M)
    if not m: return None
    return (int(m.group(1)), int(m.group(2)), m.group(4)=='-', float(m.group(5)), float(m.group(6)))
A = {n: sig_def(n, 269) for n in ["ACC_Status_ACC", "ACC_Momentenanforderung", "ACC_Verz_anf"]}
def get_sig(dat, start, length, signed):
    if len(dat) <= (start + length - 1) // 8: return 0
    val = 0
    for i in range(length):
        byte = (start + i) // 8
        bit = (start + i) % 8
        if dat[byte] & (1 << bit): val |= (1 << i)
    if signed and val & (1 << (length - 1)): val -= (1 << length)
    return val

def seg_no(p):
    m = re.search(r'--(\d+)--rlog', p)
    return int(m.group(1)) if m else -1

for route in ["00000002", "00000004"]:
    segs = sorted(glob.glob(f"/data/media/0/realdata/{route}--*--rlog.zst"))
    print(f"\n===== {route} ({len(segs)}段) =====")
    print(f"{'段':>3} {'v范围km/h':>10} {'en帧':>5} {'原厂stS分布':>16} {'原厂mom均值':>10} {'OP128帧':>6} {'判定':>8}")
    for p in segs[:15]:
        si = seg_no(p)
        try:
            lr = LogReader(p)
        except Exception:
            continue
        st = {"f": 0, "en": 0, "stS": -1, "momS": 0, "momS_sum": 0, "momS_n": 0, "v": 0.0, "vmax": 0.0, "vmin": 999.0, "tx128": 0, "stS_c": Counter()}
        for msg in lr:
            f = st["f"]
            if msg.which() == "carState":
                cs = msg.carState
                st["v"] = cs.vEgo
                if cs.cruiseState.enabled: st["en"] += 1
                st["vmax"] = max(st["vmax"], st["v"])
                st["vmin"] = min(st["vmin"], st["v"])
            elif msg.which() == "can":
                for c in msg.can:
                    if c.address == 269 and len(c.dat) >= 8:
                        d = bytes(c.dat)
                        mom = get_sig(d, A["ACC_Momentenanforderung"][0], A["ACC_Momentenanforderung"][1], False)
                        if c.src == 2:
                            st["stS"] = get_sig(d, A["ACC_Status_ACC"][0], A["ACC_Status_ACC"][1], A["ACC_Status_ACC"][2])
                            st["stS_c"][st["stS"]] += 1
                            if mom > 5:
                                st["momS_sum"] += mom
                                st["momS_n"] += 1
                        elif c.src == 128:
                            st["tx128"] += 1
            st["f"] += 1
            if st["f"] > 60000: break
        del lr
        stS_str = ",".join(f"{k}:{v}" for k, v in sorted(st["stS_c"].items()))
        mom_mean = st["momS_sum"] / st["momS_n"] if st["momS_n"] else 0
        # 判定：原厂在控制 = 原厂mom有值(>5) 且 OP 未engage(或engage少) 且 v在跑
        if st["momS_n"] > 100 and st["vmax"] > 5.0:
            tag = "原厂控制?" if st["tx128"] == 0 else ("OP代发?" if st["en"] > 100 else "混合?")
        else:
            tag = "无控制"
        print(f"{si:>3} {st['vmin']*3.6:>4.0f}-{st['vmax']*3.6:>4.0f} {st['en']:>5} {stS_str:>16} {mom_mean:>10.0f} {st['tx128']:>6} {tag:>8}")
