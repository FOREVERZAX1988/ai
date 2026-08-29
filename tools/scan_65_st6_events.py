#!/usr/bin/env python3
"""scan_65_st6_events.py — 定位 00000065 各段 bus2 ACC_05 st=6 事件
输出: 每段 st 状态序列 + st=6 事件时刻 + ACC_05 在各 bus 的出现分布
"""
import sys, glob, os
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

BASE = "/data/media/0/realdata"
ROUTE = sys.argv[1] if len(sys.argv) > 1 else "00000065"

def extract(dat, start, length):
    val = 0
    for i in range(length):
        pos = start - i
        b = pos // 8; bit = pos % 8
        v = (dat[b] >> (7 - bit)) & 1 if b < len(dat) else 0
        val = (val << 1) | v
    return val

segs = sorted(glob.glob(f"{BASE}/{ROUTE}--*--*/rlog.zst"))
print(f"=== {ROUTE} 共 {len(segs)} 段 ===", flush=True)
for sp in segs:
    seg = os.path.basename(os.path.dirname(sp)).split('--')[-1]
    bus_cnt = {}; st_seq = []; prev_st = -1; st6_events = []
    t = 0
    try:
        for m in LogReader(sp):
            if m.which() != 'can': continue
            for c in m.can:
                if c.address == 269:
                    bus_cnt[c.src] = bus_cnt.get(c.src, 0) + 1
                    if c.src == 2:
                        st = extract(c.dat, 57, 3)
                        if st != prev_st:
                            st_seq.append((t, st))
                            if st == 6: st6_events.append(t)
                            prev_st = st
                        t += 1
    except Exception as e:
        print(f"  seg{seg} 失败: {type(e).__name__}")
        continue
    if st6_events or (st_seq and any(s == 6 for _, s in st_seq)):
        print(f"seg{seg}: ACC_05 bus分布={bus_cnt} | st=6事件×{len(st6_events)} @seq {st6_events[:8]}")
        # 打印st状态机变化
        trans = "→".join(f"{s}(t{t})" for t, s in st_seq if s in (2,3,4,6) or True)[:200]
        print(f"  st序列: {trans}")
