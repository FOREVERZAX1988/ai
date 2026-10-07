#!/usr/bin/env python3
"""反驳/校准"idx 刷新率≈1Hz"：高速段 idx 静默 >=0.5 / 1.0 / 1.5 s 的帧占比
用法: probe_idx_silence_at_speed.py 00000091,0000007a,0000007b [seg4,seg5]
"""
import glob, sys
import numpy as np
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader
BASE = '/data/media/0/realdata'
WINS = (0.5, 1.0, 1.5)
acc = {w: {'moving': [0, 0], 'low': [0, 0], 'stand': [0, 0]} for w in WINS}
rate = {'moving': [0, 0.0], 'low': [0, 0.0], 'stand': [0, 0.0]}

for pref in sys.argv[1].split(','):
    only = sys.argv[2].split(',') if len(sys.argv) > 2 else None
    for f in sorted(glob.glob(f'{BASE}/{pref}--*/rlog.zst'),
                    key=lambda p: int(p.split('--')[-1].split('/')[0])):
        seg = f.split('--')[-1].split('/')[0]
        if only and seg not in only: continue
        cur = 0.0
        seq = []
        for m in LogReader(f):
            w = m.which()
            if w == 'can':
                for c in m.can:
                    if c.src == 2 and c.address == 780 and len(c.dat) >= 7:
                        cur = float((c.dat[3] | (c.dat[4] << 8)) & 0x3FF)
            elif w == 'carState':
                seq.append((m.logMonoTime/1e9, float(m.carState.vEgo), cur))
        if len(seq) < 100: continue
        # 每个 sample 的"距上次变化的时长"
        age = []
        last_t = seq[0][0]; last_v = None
        for t, v, ix in seq:
            if ix != last_v:
                last_v = ix; last_t = t
            age.append((t, v, ix, t - last_t))
        for t, v, ix, a in age:
            if not (1 <= ix <= 1020): continue
            b = 'moving' if v > 3 else ('low' if v > 0.3 else 'stand')
            rate[b][0] += 1
            for w in WINS:
                if a >= w: acc[w][b][0] += 1
                acc[w][b][1] += 1
            if a >= 1.0: acc[1.0][b][1] += 0
        # 变化率
        chg = sum(1 for k in range(1, len(seq)) if seq[k][2] != seq[k-1][2] and 1 <= seq[k][2] <= 1020)
        rate['moving'][1] += chg  # 简化：全局
        print(f'  {pref} seg{seg}: 变化 {chg} 次 / {seq[-1][0]-seq[0][0]:.0f}s = {chg/(seq[-1][0]-seq[0][0]):.2f} 次/s')

print()
for b, name in (('moving', 'v>3 m/s'), ('low', '0.3-3 m/s'), ('stand', '<0.3 m/s')):
    if not acc[0.5][b][1]: continue
    n = acc[0.5][b][1]
    s = ' | '.join(f'静默>={w}s: {100*acc[w][b][0]/n:5.1f}%' for w in WINS)
    print(f'{name:11s} n={n:7d}  {s}')
