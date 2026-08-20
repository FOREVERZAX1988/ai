#!/usr/bin/env python3
"""力矩开合（喘气感）验证：无车巡航时 mom 是否周期性归零（给油-收油循环）
场景：用户"周边没车也一会加速一会减速"——如果 mom 反复从高位归零再回高位，
引擎声音/车身姿态=一冲一冲（速度不振荡，但力矩开合）"""
import glob, sys, re
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

DBC = "opendbc_repo/opendbc/dbc/vw_mlb.dbc"
dbc_text = open(DBC, encoding="latin-1").read()
def sig_def(name, msg_id):
    m = re.search(rf'^ SG_ {name} : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)', dbc_text, re.M)
    if not m: return None
    return (int(m.group(1)), int(m.group(2)), m.group(4)=='-', float(m.group(5)), float(m.group(6)))
A = {n: sig_def(n, 269) for n in ["ACC_Momentenanforderung", "ACC_Verz_anf"]}
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
print("窗口：无车(lead>60m) + v>8m/s + 激活 + 连续3s")
print("指标：mom<30帧占比（收油）、mom跳变>50（开合）、aTarget抖动(0.05~0.3)占比\n")

wins = []
for si in range(15):
    lr = LogReader(segs[si])
    st = {"f": 0, "en": False, "v": 0.0, "lead": 999.0, "at": 0.0, "mom": 0}
    win = []
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            cs = msg.carState
            st["en"] = cs.cruiseState.enabled
            st["v"] = cs.vEgo
        elif msg.which() == "longitudinalPlan":
            st["at"] = msg.longitudinalPlan.aTarget
        elif msg.which() == "modelV2":
            if len(msg.modelV2.leadsV3) > 0:
                st["lead"] = msg.modelV2.leadsV3[0].x[0]
        elif msg.which() == "can":
            for c in msg.can:
                if c.address == 269 and c.src == 128 and len(c.dat) >= 8:
                    d = bytes(c.dat)
                    st["mom"] = get_sig(d, A["ACC_Momentenanforderung"][0], A["ACC_Momentenanforderung"][1], False)
        if st["en"] and st["v"] > 8.0 and st["lead"] > 60.0 and f % 2 == 0:
            win.append((f, st["mom"], st["at"], st["v"]))
            if len(win) > 150: win.pop(0)
            if len(win) == 150:
                moms = [m for _, m, _, _ in win]
                ats = [a for _, _, a, _ in win]
                # mom 归零率（<30 视为收油/滑行）
                zr = sum(1 for m in moms if m < 30) / 150
                # mom 开合跳变（相邻差>50）
                jumps = sum(1 for i in range(1, len(moms)) if abs(moms[i] - moms[i-1]) > 50)
                # aTarget 抖动（0.05~0.3 之间反复）
                dither = sum(1 for a in ats if 0.05 < a < 0.3) / 150
                # 高力矩段（>90）与归零段的交替
                hi = [m > 90 for m in moms]
                hi_flip = sum(1 for i in range(1, len(hi)) if hi[i] != hi[i-1])
                if zr > 0.15 and (jumps >= 3 or hi_flip >= 3):
                    wins.append((si, win[0][0], zr, jumps, hi_flip, dither, st["v"]*3.6, moms[-1]))
                win = []
        st["f"] += 1
    del lr

print(f"力矩开合窗口（3s内mom归零>15%且开合≥3次）: {len(wins)} 个")
print(f"{'段':>2} {'帧':>6} {'收油率':>6} {'跳变':>3} {'开合':>3} {'a抖动':>6} {'vkmh':>5}")
for w in wins[:20]:
    print(f"{w[0]:>2} {w[1]:>6} {w[2]:>6.1%} {w[3]:>3} {w[4]:>3} {w[5]:>6.1%} {w[6]:>5.0f}")
if wins:
    print("\n→ 存在'给油-收油'循环（喘气感）——修复方向：aTarget死区/mom平滑")
else:
    print("\n→ 无车巡航力矩平稳（无喘气）——'循环'感可能来自跟车/起步等动态场景")
