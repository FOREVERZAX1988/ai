#!/usr/bin/env python3
"""_probe_acc02_superset.py <route 目录前缀> [seg...]

回答"bus128(OP代发) 的 ACC_02 目标信号是不是 bus2(原厂) 的超集"。
先报各自报文速率（原厂 25Hz / OP 16.7Hz —— 直接比"帧数"会被速率差异误导），
再做速率无关的逐帧配对比较（OP 每帧去找 0.25s 内最近的原厂帧）：
  双方都有目标 / 仅原厂有目标 / 仅OP有目标 / 都无目标
"仅原厂有" = 原厂雷达有目标但 OP 显示与控制的 lead 都没有（2.A 之后仪表=控制源，
所以这类目标仪表也不再显示）。
"""
import sys, glob, os, bisect
sys.path.insert(0, '/data/openpilot')
from openpilot.tools.lib.logreader import LogReader


def g(x, s, n):
    return (int.from_bytes(x, 'little') >> s) & ((1 << n) - 1)


prefix = sys.argv[1]
segs = sys.argv[2:] or [os.path.basename(p.rstrip('/')).split('--')[-1]
                        for p in sorted(glob.glob(prefix + '--*'))]

for seg in segs:
    p = glob.glob(f"{prefix}--{seg}/rlog.zst")
    if not p:
        continue
    st, op = [], []
    for e in LogReader(p[0]):
        if e.which() != 'can':
            continue
        for m in e.can:
            if m.address != 780:
                continue
            x = bytes(m.dat)
            rec = (e.logMonoTime / 1e9, g(x, 24, 10), g(x, 46, 3) & 3)
            (st if m.src == 2 else op).append(rec)
    if len(st) < 10 or len(op) < 10:
        continue
    dur = st[-1][0] - st[0][0]
    stt = [a[0] for a in st]
    c = {'both': 0, 'only_st': 0, 'only_op': 0, 'none': 0}
    for t, idx, rel in op:
        i = bisect.bisect_right(stt, t) - 1
        if i < 0 or t - st[i][0] > 0.25:
            continue
        hs, ho = st[i][1] > 0, idx > 0
        c['both' if hs and ho else 'only_st' if hs else 'only_op' if ho else 'none'] += 1
    print(f"seg{seg} {dur:.0f}s | 原厂 {len(st)}帧({len(st)/dur:.1f}Hz, idx>0={sum(1 for a in st if a[1] > 0)}) "
          f"| OP {len(op)}帧({len(op)/dur:.1f}Hz, idx>0={sum(1 for a in op if a[1] > 0)})")
    print(f"        配对: 双方都有={c['both']} 仅原厂有={c['only_st']} 仅OP有={c['only_op']} 都无={c['none']}")
