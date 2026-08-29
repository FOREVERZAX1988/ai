#!/usr/bin/env python3
"""输出 OP(bus128) 与原厂(bus2) 的 st 状态机变化时间线 + carState(gas/vego/brk)"""
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
print(f"=== 00000065 seg{seg} st时间线 ===", flush=True)
last2 = last1 = None
st2_seq = []; st1_seq = []
seq = 0
for m in LogReader(sp):
    if m.which() != 'can': continue
    for c in m.can:
        if c.address == 269:
            st = extract(c.dat, 57, 3)
            verz = extract(c.dat, 32, 11)*0.005 - 7.22
            axg = extract(c.dat, 48, 9)*0.024 - 2.016
            loes = extract(c.dat, 43, 1)
            if c.src == 2:
                if last2 is None or st != last2:
                    st2_seq.append((seq, st, verz, axg, loes))
                last2 = st
            elif c.src == 128:
                if last1 is None or st != last1:
                    st1_seq.append((seq, st, verz, axg, loes))
                last1 = st
    seq += 1
print(f"\n--- bus2(原厂) st 变化 ({len(st2_seq)} 次) ---")
for s in st2_seq[:30]:
    print(f"  seq{s[0]:>6}: st={s[1]} verz={s[2]:>6.2f} axG={s[3]:>6.2f} loes={s[4]}")
print(f"\n--- bus128(OP) st 变化 ({len(st1_seq)} 次) ---")
for s in st1_seq[:30]:
    print(f"  seq{s[0]:>6}: st={s[1]} verz={s[2]:>6.2f} axG={s[3]:>6.2f} loes={s[4]}")
