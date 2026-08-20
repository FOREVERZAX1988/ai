#!/usr/bin/env python3
"""4f jerk 事件扫描：aTarget 在 ~0.2s 内跳变 >0.25 m/s² 的事件
区分"突然加速"（快速爬升）vs"突然减速"（verz 快速介入）
输出：段/帧/v/lead/a_before→a_after/类型 + 每段事件统计"""
import glob, sys, re
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

DBC = "opendbc_repo/opendbc/dbc/vw_mlb.dbc"
dbc_text = open(DBC, encoding="latin-1").read()
def sig_def(name, msg_id):
    m = re.search(rf'^ SG_ {name} : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)', dbc_text, re.M)
    if not m: return None
    return (int(m.group(1)), int(m.group(2)), m.group(4)=='-', float(m.group(5)), float(m.group(6)))
A = {n: sig_def(n, 269) for n in ["ACC_Verz_anf", "ACC_Momentenanforderung"]}
def get_sig(dat, start, length, signed):
    if len(dat) <= (start + length - 1) // 8: return 0
    val = 0
    for i in range(length):
        byte = (start + i) // 8
        bit = (start + i) % 8
        if dat[byte] & (1 << bit): val |= (1 << i)
    if signed and val & (1 << (length - 1)): val -= (1 << length)
    return val

segs = sorted(glob.glob("/data/media/0/realdata/0000004f--*/rlog.zst"))
print(f"{'段':>2} {'帧':>7} {'vkmh':>5} {'lead':>5} | {'a前→a后':>11} {'d(0.2s)':>7} {'类型':>4} | {'mom':>4} {'verz':>5}")
print("-"*75)
tot = 0
for si in range(15):
    lr = LogReader(segs[si])
    st = {"f": 0, "v": 0.0, "en": False, "lead_d": 999.0, "mom": 0, "verz": 0.0}
    hist = []
    n_ev = 0
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            st["v"] = msg.carState.vEgo
            st["en"] = msg.carState.cruiseState.enabled
        elif msg.which() == "longitudinalPlan" and st["en"]:
            at = msg.longitudinalPlan.aTarget
            hist.append((f, at))
            if len(hist) > 21: hist.pop(0)
            if len(hist) == 21 and hist[-1][0] - hist[0][0] <= 25:
                d = at - hist[0][1]
                if abs(d) > 0.25:
                    typ = "加速" if d > 0 else "减速"
                    n_ev += 1; tot += 1
                    if n_ev <= 8:
                        print(f"{si:>2} {f:>7} {st['v']*3.6:>5.0f} {st['lead_d']:>5.0f} | {hist[0][1]:>5.2f}→{at:>5.2f} {d:>+7.2f} {typ:>4} | {st['mom']:>4.0f} {st['verz']:>5.2f}")
                    hist = []
        elif msg.which() == "modelV2":
            if len(msg.modelV2.leadsV3) > 0:
                st["lead_d"] = msg.modelV2.leadsV3[0].x[0]
        elif msg.which() == "can":
            for c in msg.can:
                if c.address == 269 and c.src == 128 and len(c.dat) >= 8:
                    d = bytes(c.dat)
                    st["verz"] = get_sig(d, A["ACC_Verz_anf"][0], A["ACC_Verz_anf"][1], A["ACC_Verz_anf"][2]) * 0.005 - 7.22
                    st["mom"] = get_sig(d, A["ACC_Momentenanforderung"][0], A["ACC_Momentenanforderung"][1], A["ACC_Momentenanforderung"][2])
        st["f"] += 1
    del lr
    print(f"  段{si}: jerk事件 {n_ev} 个")
print(f"\n总计 {tot} 个 jerk 事件（阈值0.25/0.2s）")
