#!/usr/bin/env python3
"""idx(bus2 ACC_02=0x30C) 刷新率实测：只统计有效 idx(1..1020)，按 vEgo 分带。
输出: 报文Hz(按 bus2 ACC_02 帧) / idx 变化次/s / 不变 run 时长分位 / 最长不变
用法: probe_idx_rate2.py 00000091,0000007a
"""
import glob, sys
from collections import defaultdict
import numpy as np
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader
BASE = '/data/media/0/realdata'

def band_of(v):
    return 'moving>3' if v > 3.0 else ('low0.3-3' if v > 0.3 else 'standstill<0.3')

res = defaultdict(lambda: dict(frames=0, span=0.0, chg=0, runs=[], maxrun=0.0))
for pref in sys.argv[1].split(','):
    print(f'=== {pref} ===')
    for f in sorted(glob.glob(f'{BASE}/{pref}--*/rlog.zst'),
                    key=lambda p: int(p.split('--')[-1].split('/')[0])):
        segno = f.split('--')[-1].split('/')[0]
        cur_idx = 0.0
        seq = []   # (t, vEgo or None, idx_snapshot)
        for m in LogReader(f):
            w = m.which()
            if w == 'can':
                for c in m.can:
                    if c.src == 2 and c.address == 780 and len(c.dat) >= 7:
                        cur_idx = float((c.dat[3] | (c.dat[4] << 8)) & 0x3FF)
            elif w == 'carState':
                seq.append((m.logMonoTime/1e9, float(m.carState.vEgo), cur_idx))
        if len(seq) < 50: continue
        # 分带聚合
        last = {}   # band -> (idx, t_start_of_run)
        bandcnt = defaultdict(int); bandspan = defaultdict(float); bandchg = defaultdict(int)
        t0b = {}; t1b = {}
        for t, v, ix in seq:
            if not (1 <= ix <= 1020):
                last.pop(band_of(v), None)
                continue
            b = band_of(v)
            bandcnt[b] += 1
            t0b.setdefault(b, t); t1b[b] = t
            if b in last and ix == last[b][0]:
                pass
            else:
                if b in last:
                    dur = t - last[b][1]
                    res[b]['runs'].append(dur)
                    res[b]['maxrun'] = max(res[b]['maxrun'], dur)
                    bandchg[b] += 1
                last[b] = (ix, t)
        for b in bandcnt:
            res[b]['frames'] += bandcnt[b]
            res[b]['span'] += (t1b[b] - t0b[b])
            res[b]['chg'] += bandchg[b]
        out = []
        for b in ('moving>3', 'low0.3-3', 'standstill<0.3'):
            if bandcnt.get(b, 0) < 20: continue
            span = max(t1b[b]-t0b[b], 1e-6)
            out.append(f'{b}: {bandcnt[b]/span:5.1f}Hz报文 {bandchg[b]/span:6.2f}变/s 最长不变{max([r for r in res[b]["runs"]][-200:] or [0]):.1f}s')
        print(f'  seg{segno}: ' + ' | '.join(out))

print()
print('=== 汇总（全部 route）===')
for b in ('moving>3', 'low0.3-3', 'standstill<0.3'):
    d = res.get(b)
    if not d or d['span'] <= 0:
        print(f'{b:14s}: 无数据'); continue
    r = np.array(d['runs']) if d['runs'] else np.array([0.0])
    print(f'{b:14s}: 有效idx帧 {d["frames"]:7d} 跨度 {d["span"]:7.0f}s | '
          f'报文 {d["frames"]/d["span"]:5.1f}Hz | idx变化 {d["chg"]/d["span"]:6.2f}次/s '
          f'(平均 {d["span"]/max(d["chg"],1):.3f}s/次) | 不变run P50={np.percentile(r,50):.2f}s '
          f'P90={np.percentile(r,90):.2f}s P99={np.percentile(r,99):.2f}s MAX={r.max():.1f}s')
