#!/usr/bin/env python3
"""找 st 转折点(3/4→6/7)，显示转折前正常期 vs 降级期的 OP/原厂全信号对比"""
import sys, glob, os
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
BASE = "/data/media/0/realdata"

def extract(dat, start, length):
    val = 0
    for i in range(length):
        pos = start - i
        b = pos // 8; bit = pos % 8
        v = (dat[b] >> (7 - bit)) & 1 if b < len(dat) else 0
        val = (val << 1) | v
    return val

seg = sys.argv[1]
sp = glob.glob(f"{BASE}/00000065--*--{seg}/rlog.zst")[0]
print(f"=== 00000065 seg{seg}: st转折点分析 ===", flush=True)
all2 = []; all1 = []  # (idx, st, verz, mom, axg, loes, fv, fm)
bus_cnt = {}
for m in LogReader(sp):
    if m.which() != 'can': continue
    for c in m.can:
        if c.address == 269:
            bus_cnt[c.src] = bus_cnt.get(c.src, 0) + 1
            st = extract(c.dat, 57, 3)
            verz = extract(c.dat, 32, 11)*0.005 - 7.22
            mom = extract(c.dat, 16, 10)
            loes = extract(c.dat, 43, 1)
            fv = extract(c.dat, 13, 1)
            fm = extract(c.dat, 12, 1)
            axg = extract(c.dat, 48, 9)*0.024 - 2.016
            r = (st, verz, mom, axg, loes, fv, fm)
            if c.src == 2: all2.append(r)
            elif c.src == 128: all1.append(r)
print(f"ACC_05 bus分布: {bus_cnt}")
# 找原厂 st 从 3/4 → 6/7 的转折点
turns = []
for i in range(1, len(all2)):
    if all2[i][0] in (6, 7) and all2[i-1][0] in (3, 4):
        turns.append(i)
print(f"st 转折点(3/4→6/7): {len(turns)} 处 @帧 {turns[:10]}")
for ti in turns[:3]:
    a = max(0, ti-20)
    print(f"\n--- 转折 @帧{ti} (显示{ti-20}~{ti+3}) ---")
    print(f"   {'帧':>4} | bus2: st verz  mom  axG   loes fv fm | bus128: st verz  mom  axG   loes fv fm")
    for i in range(a, min(ti+4, len(all2))):
        s2 = all2[i] if i < len(all2) else None
        s1 = all1[i] if i < len(all1) else None
        line = f"   {i:>4} |"
        if s2:
            line += f"  T  {s2[0]:>2} {s2[1]:>5.2f} {s2[2]:>3} {s2[3]:>5.2f} {s2[4]:>2} {s2[5]} {s2[6]}"
        else:
            line += "  ."
        if s1:
            line += f" |  O  {s1[0]:>2} {s1[1]:>5.2f} {s1[2]:>3} {s1[3]:>5.2f} {s1[4]:>2} {s1[5]} {s1[6]}"
        mark = " <<<转折" if i == ti else ""
        print(line + mark)
