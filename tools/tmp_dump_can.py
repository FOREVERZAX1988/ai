#!/usr/bin/env python3
"""dump 指定 route 的 0x10b/0x10d/0x780 原始帧 (src, hex, count) + 时间窗。"""
import sys, os
from collections import Counter
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader
BASE = '/data/media/0/realdata'
pre = sys.argv[1]
t0 = float(sys.argv[2]); t1 = float(sys.argv[3])
segs = sorted(d for d in os.listdir(BASE) if d.startswith(pre) and os.path.isfile(f'{BASE}/{d}/rlog.zst'))
for seg in segs:
    tt = 0.0
    c = Counter()
    for m in LogReader(f'{BASE}/{seg}/rlog.zst'):
        w = m.which()
        if w == 'carState':
            tt = float(m.logMonoTime) / 1e9
        elif w == 'can':
            for f in m.can:
                if f.address in (0x10b, 0x10d, 0x780) and t0 <= tt <= t1:
                    c[(hex(f.address), f.src, bytes(f.dat).hex())] += 1
    if c:
        print(f'--- {seg}')
        for k, v in sorted(c.items()):
            print(f'  {k[0]} src={k[1]} dat={k[2]}  x{v}')
