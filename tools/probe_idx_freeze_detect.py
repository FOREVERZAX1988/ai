#!/usr/bin/env python3
"""比较两种"idx 冻结"判据在 行车/低速/静止 三个速度带上的命中覆盖率：
 (a) 严格：最近 0.5s 内 idx 完全不变
 (b) 准冻结：最近 0.5s 内 |Δidx| <= 2（抗末位抖动）
另外直接测 bus2 src=2 ACC_02 的真实报文帧率(Hz)与有效 idx 变化率。
用法: probe_idx_freeze_detect.py 00000091,0000007a,0000007b
"""
import glob, sys
from collections import defaultdict, deque
import numpy as np
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader
BASE = '/data/media/0/realdata'
WIN = 0.5

def band_of(v):
    return 'moving>3' if v > 3.0 else ('low0.3-3' if v > 0.3 else 'standstill<0.3')

acc = defaultdict(lambda: dict(n=0, a=0, b=0))
canrate = defaultdict(lambda: dict(frames=0, span=0.0))
for pref in sys.argv[1].split(','):
    print(f'=== {pref} ===')
    for f in sorted(glob.glob(f'{BASE}/{pref}--*/rlog.zst'),
                    key=lambda p: int(p.split('--')[-1].split('/')[0])):
        segno = f.split('--')[-1].split('/')[0]
        cur = 0.0
        seq = []
        cants = []
        t_first = t_last = None
        for m in LogReader(f):
            w = m.which()
            if w == 'can':
                for c in m.can:
                    if c.src == 2 and c.address == 780 and len(c.dat) >= 7:
                        cur = float((c.dat[3] | (c.dat[4] << 8)) & 0x3FF)
                        cants.append(m.logMonoTime/1e9)
            elif w == 'carState':
                seq.append((m.logMonoTime/1e9, float(m.carState.vEgo), cur))
        if len(seq) < 50: continue
        if cants:
            s = cants[-1] - cants[0]
            if s > 1: canrate['all']['frames'] += len(cants); canrate['all']['span'] += s
        win = deque()
        per = defaultdict(lambda: [0, 0, 0])
        for t, v, ix in seq:
            if not (1 <= ix <= 1020):
                win.clear(); continue
            win.append((t, ix))
            while win and t - win[0][0] > WIN: win.popleft()
            if len(win) < 5 or t - win[0][0] < WIN * 0.8: continue
            vals = [x[1] for x in win]
            strict = (max(vals) == min(vals))
            quasi = (max(vals) - min(vals) <= 2)
            b = band_of(v)
            acc[b]['n'] += 1
            acc[b]['a'] += 1 if strict else 0
            acc[b]['b'] += 1 if quasi else 0
            per[b][0] += 1; per[b][1] += 1 if strict else 0; per[b][2] += 1 if quasi else 0
        out = []
        for b in ('moving>3', 'low0.3-3', 'standstill<0.3'):
            n, a, q = per[b]
            if n < 20: continue
            out.append(f'{b}: 严格冻结 {100*a/n:4.1f}% / 准冻结(|Δ|<=2) {100*q/n:4.1f}% (n={n})')
        print(f'  seg{segno}: ' + ' || '.join(out))

print()
print('=== ACC_02(0x30C) bus2 src=2 真实报文帧率 ===')
for k, d in canrate.items():
    if d['span'] > 0:
        print(f'  {d["frames"]} 帧 / {d["span"]:.0f} s = {d["frames"]/d["span"]:.2f} Hz')
print()
print('=== 冻结判据覆盖率汇总 ===')
for b in ('moving>3', 'low0.3-3', 'standstill<0.3'):
    d = acc[b]
    if not d['n']: continue
    print(f'{b:14s}: n={d["n"]:6d} | (a)严格不变命中 {100*d["a"]/d["n"]:5.1f}% | '
          f'(b)|Δidx|<=2 命中 {100*d["b"]/d["n"]:5.1f}%')
