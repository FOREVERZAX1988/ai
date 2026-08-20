#!/usr/bin/env python3
"""深挖 0000004f v3：SnG停车（OP代发src=128 vs 原厂src=2）+ 摇晃窗口"""
import glob, sys, re
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

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

D = {n: sig_def(n, 269) for n in ["ACC_Momentenanforderung", "ACC_Verz_anf", "ACC_Anhalten", "ACC_Status_ACC"]}
print("ACC_05 defs:", {k: (v[:2] if v else None) for k, v in D.items()})

def get_sig(dat, start, length, signed):
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

def dump_window(si, f0, f1, label, every=25):
    try:
        lr = LogReader(segs[si])
    except Exception:
        return
    print(f"\n--- {label} (段{si} 帧{f0}-{f1}) ---")
    print(f"{'帧':>7} {'vEgo':>5} {'aEgo':>5} {'aTgt':>5} {'steer':>5} {'anhO':>4} {'anhS':>4} {'momO':>5} {'momS':>5} {'stO':>3} {'stS':>3} {'verzO':>6} {'leadD':>6} {'leadV':>5}")
    st = {"v": 0, "a": 0, "at": 0, "steer": 0, "anhO": -1, "anhS": -1, "momO": -99, "momS": -99, "stO": -1, "stS": -1, "verzO": 99, "ld": 0, "lv": 0, "f": 0}
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            cs = msg.carState
            st["v"] = cs.vEgo; st["a"] = cs.aEgo; st["steer"] = cs.steeringAngleDeg
        elif msg.which() == "longitudinalPlan":
            st["at"] = msg.longitudinalPlan.aTarget
        elif msg.which() == "modelV2":
            if len(msg.modelV2.leadsV3) > 0:
                st["ld"] = msg.modelV2.leadsV3[0].x[0]
                st["lv"] = msg.modelV2.leadsV3[0].v[0]
        elif msg.which() == "can":
            for c in msg.can:
                if c.address == 269:
                    d = bytes(c.dat)
                    if c.src == 128:
                        st["anhO"] = get_sig(d, D["ACC_Anhalten"][0], D["ACC_Anhalten"][1], D["ACC_Anhalten"][2])
                        st["momO"] = get_sig(d, D["ACC_Momentenanforderung"][0], D["ACC_Momentenanforderung"][1], D["ACC_Momentenanforderung"][2])
                        st["stO"] = get_sig(d, D["ACC_Status_ACC"][0], D["ACC_Status_ACC"][1], D["ACC_Status_ACC"][2])
                        st["verzO"] = get_sig(d, D["ACC_Verz_anf"][0], D["ACC_Verz_anf"][1], D["ACC_Verz_anf"][2]) * 0.005 - 7.22
                    elif c.src == 2:
                        st["anhS"] = get_sig(d, D["ACC_Anhalten"][0], D["ACC_Anhalten"][1], D["ACC_Anhalten"][2])
                        st["momS"] = get_sig(d, D["ACC_Momentenanforderung"][0], D["ACC_Momentenanforderung"][1], D["ACC_Momentenanforderung"][2])
                        st["stS"] = get_sig(d, D["ACC_Status_ACC"][0], D["ACC_Status_ACC"][1], D["ACC_Status_ACC"][2])
        if f0 <= f <= f1 and f % every == 0:
            print(f"{f:>7} {st['v']*3.6:>5.0f} {st['a']:>5.2f} {st['at']:>5.2f} {st['steer']:>5.0f} "
                  f"{st['anhO']:>4} {st['anhS']:>4} {st['momO']:>5.0f} {st['momS']:>5.0f} {st['stO']:>3} {st['stS']:>3} "
                  f"{st['verzO']:>6.2f} {st['ld']:>6.1f} {st['lv']:>5.1f}")
        st["f"] += 1
    del lr

# ① SnG 段1：前车起步@8027→OP请求@8137（前车leadV从0.2→3.1）
dump_window(1, 7800, 9200, "① SnG 段1：停车中前车起步(leadV 0.2→3.1), OP请求正a, 车不动")

# ② 摇晃 段8：找正负交替密集窗口（先看整体aEgo/mom走势）
dump_window(8, 2000, 4500, "② 摇晃 段8 (momO/verzO vs aEgo)", every=30)
