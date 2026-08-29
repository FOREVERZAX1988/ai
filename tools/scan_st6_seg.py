#!/usr/bin/env python3
"""单段扫描 st=6 事件上下文: bus2原厂 vs bus128 OP 全信号对比"""
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
print(f"=== 00000065 seg{seg} ===", flush=True)
buf2 = []; buf1 = []; events = []; prev_st = -1; cur = 0
for m in LogReader(sp):
    if m.which() != 'can': continue
    for c in m.can:
        if c.address == 269:
            st = extract(c.dat, 57, 3)
            verz = extract(c.dat, 32, 11)*0.005 - 7.22
            mom = extract(c.dat, 16, 10)
            loes = extract(c.dat, 43, 1)
            fv = extract(c.dat, 13, 1)
            fm = extract(c.dat, 12, 1)
            axg = extract(c.dat, 48, 9)*0.024 - 2.016
            if c.src == 2:
                buf2.append((cur, st, verz, mom, axg, loes, fv, fm))
                if st != prev_st:
                    if st == 6:
                        events.append(cur)
                    prev_st = st
            elif c.src == 128:
                buf1.append((cur, st, verz, mom, axg, loes, fv, fm))
            cur += 1
if not events:
    print("无 st=6 事件")
    sys.exit(0)
print(f"st=6事件 {len(events)} 处 @ seq {events[:10]}")
for ev in events[:3]:
    print(f"\n--- st=6 @seq{ev} 前35帧对比 ---")
    print("  bus2(原厂):    st verz  mom  axG   loes fv fm")
    print("  bus128(OP):    st verz  mom  axG   loes fv fm")
    # 对齐最近35帧
    b2 = [x for x in buf2 if x[0] <= ev][-35:]
    b1 = [x for x in buf1 if x[0] <= ev][-35:]
    n = max(len(b2), len(b1))
    for i in range(n):
        line = ""
        if i < len(b2):
            c0, st, vz, mo, ax, lo, f, fm = b2[i]
            line += f"  T  {st:>2} {vz:>5.2f} {mo:>3} {ax:>5.2f} {lo:>2} {f} {fm}"
        else:
            line += "  ."
        if i < len(b1):
            c0, st, vz, mo, ax, lo, f, fm = b1[i]
            line += f"  |  O  {st:>2} {vz:>5.2f} {mo:>3} {ax:>5.2f} {lo:>2} {f} {fm}"
        mark = " <<< st=6" if i == len(b2)-1 and b2[-1][1] == 6 else ""
        print(line + mark)
