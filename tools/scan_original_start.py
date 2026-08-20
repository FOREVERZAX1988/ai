#!/usr/bin/env python3
"""原厂 ACC 行为对比：从 0002/0004/0049 找"停车→踩油门→车动"窗口
深挖原厂帧（src=2）的 st/anh/verz/mom/FM/FV/Loeseanf 时序
回答：原厂踩油门时 verz 发不发？（A'依据）mom 什么时候给？（A依据）"""
import glob, sys
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

def sigs(d):
    out = {}
    out["st"] = (d[7] >> 1) & 0x7       # ACC_Status_ACC 57|3
    out["anh"] = (d[7] >> 0) & 0x1      # ACC_Anhalten 56|1
    out["mom"] = d[2] | ((d[3] & 0x03) << 8)  # ACC_Momentenanforderung 16|10
    raw_v = d[4] | ((d[5] & 0x07) << 8)
    if raw_v & 0x400: raw_v -= 0x800
    out["verz"] = round(raw_v * 0.005 - 7.22, 2)  # ACC_Verz_anf 32|11
    out["fm"] = (d[1] >> 4) & 0x1       # ACC_Freigabe_Momentenanf 12|1
    out["fv"] = (d[1] >> 5) & 0x1       # ACC_Freigabe_Verzanf 13|1
    out["loes"] = (d[5] >> 3) & 0x1     # ACC_Loeseanforderung 43|1
    return out

def find_window(route, max_segs):
    """找 en + v<0.1 + gas 0→1 + 200帧内 v>0.5 的窗口"""
    segs = sorted(glob.glob(f"/data/media/0/realdata/{route}--*/rlog.zst"))
    for si in range(min(len(segs), max_segs)):
        try:
            lr = LogReader(segs[si])
        except Exception:
            continue
        st = {"f": 0, "gas": 0, "pg": 0, "en": 0, "v": 0.0}
        gas_start = None
        for msg in lr:
            f = st["f"]
            if msg.which() == "carState":
                cs = msg.carState
                st["gas"] = cs.gasPressed
                st["en"] = cs.cruiseState.enabled
                st["v"] = cs.vEgo
                if gas_start is not None and st["v"] > 0.5:
                    del lr
                    return si, gas_start, f
            if st["gas"] and st["pg"] == 0 and st["en"] and st["v"] < 0.1:
                gas_start = f
            if gas_start is not None and st["pg"] == 1 and st["gas"] == 0:
                gas_start = None
            st["pg"] = st["gas"]
            st["f"] += 1
        del lr
    return None, None, None

def dump_window(route, si, g0, g1, label):
    segs = sorted(glob.glob(f"/data/media/0/realdata/{route}--*/rlog.zst"))
    lr = LogReader(segs[si])
    st = {"f": 0, "gas": 0, "en": 0, "v": 0.0}
    src2 = {"st": -1, "anh": -1, "verz": 99, "mom": -1, "fm": -1, "fv": -1, "loes": -1}
    has128 = False
    print(f"\n===== {label} 段{si} 踩油门@{g0} 车动@{g1}（{(g1-g0)/100:.1f}s）=====")
    print(f"{'帧':>6} {'gas':>3} {'v':>4} | 原厂帧: {'st':>2} {'anh':>3} {'verz':>6} {'mom':>4} {'fm':>2} {'fv':>2} {'loes':>3} | OP128")
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            cs = msg.carState
            st["gas"] = cs.gasPressed; st["en"] = cs.cruiseState.enabled; st["v"] = cs.vEgo
        elif msg.which() == "can":
            for c in msg.can:
                if c.address == 269 and len(c.dat) >= 8:
                    s = sigs(bytes(c.dat))
                    if c.src == 2:
                        src2 = s
                    elif c.src == 128:
                        has128 = True
        if g0 - 40 <= f <= g1 + 40 and f % 5 == 0:
            print(f"{f:>6} {st['gas']:>3} {st['v']*3.6:>4.0f} | {src2['st']:>2} {src2['anh']:>3} {src2['verz']:>6} {src2['mom']:>4} {src2['fm']:>2} {src2['fv']:>2} {src2['loes']:>3} | {'有' if has128 else '-'}")
        st["f"] += 1
        if f > g1 + 40: break
    del lr

for route, label, max_segs in [("00000002", "0002 原厂ACC", 30), ("00000004", "0004 原厂ACC", 12), ("00000049", "0049 官方master", 12)]:
    si, g0, g1 = find_window(route, max_segs)
    if g0:
        print(f"{label}: 找到窗口 段{si} 踩油门@{g0} 车动@{g1}")
        dump_window(route, si, g0, g1, label)
    else:
        print(f"{label}: 未找到窗口（可能无停车踩油门起步场景或段数不足）")
