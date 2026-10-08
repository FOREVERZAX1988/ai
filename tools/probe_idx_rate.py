#!/usr/bin/env python3
"""idx(bus2 ACC_02 = 0x30C) 刷新率 / 数值变化率 实测
- 报文帧率 (Hz)  vs  数值变化率 (changes/s)  vs  最快两次变化间隔
- 按 vEgo 分带：moving(>3) / low(0.3~3) / standstill(<0.3)
用法: probe_idx_rate.py 00000091 0000007a [seglist]
"""
import glob, os, sys
from collections import defaultdict
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader
BASE = '/data/media/0/realdata'

def scan(f):
    """返回 bus2 ACC_02 帧序列 [(t, idx)]，以及 carState 序列 [(t,vEgo)]"""
    msgs, vs = [], []
    for m in LogReader(f):
        w = m.which()
        if w == 'can':
            for c in m.can:
                if c.src == 2 and c.address == 780 and len(c.dat) >= 7:
                    msgs.append((m.logMonoTime / 1e9, float((c.dat[3] | (c.dat[4] << 8)) & 0x3FF)))
        elif w == 'carState':
            vs.append((m.logMonoTime / 1e9, float(m.carState.vEgo)))
    return msgs, vs

def vat(vs, t):
    lo, hi = 0, len(vs) - 1
    if not vs: return 0.0
    if t <= vs[0][0]: return vs[0][1]
    if t >= vs[-1][0]: return vs[-1][1]
    while lo < hi:
        mid = (lo + hi) // 2
        if vs[mid][0] < t: lo = mid + 1
        else: hi = mid
    return vs[lo][1]

for pref in sys.argv[1].split(','):
    segs = sys.argv[2].split(',') if len(sys.argv) > 2 else None
    files = sorted(glob.glob(f'{BASE}/{pref}--*/rlog.zst'),
                   key=lambda p: int(p.split('--')[-1].split('/')[0]))
    print(f'=== {pref} : {len(files)} segs ===')
    tot = defaultdict(lambda: dict(frames=0, span=0.0, chg=0, gaps=[]))
    for f in files:
        segno = f.split('--')[-1].split('/')[0]
        if segs and segno not in segs: continue
        msgs, vs = scan(f)
        if len(msgs) < 50: continue
        band_frames = defaultdict(int)
        band_ts = defaultdict(list)
        for t, ix in msgs:
            v = vat(vs, t)
            band = 'moving' if v > 3.0 else ('low' if v > 0.3 else 'standstill')
            band_frames[band] += 1
            band_ts[band].append((t, ix))
        line = []
        for band in ('moving', 'low', 'standstill'):
            ts = band_ts[band]
            if len(ts) < 30: continue
            span = ts[-1][0] - ts[0][0]
            chg = sum(1 for k in range(1, len(ts)) if ts[k][1] != ts[k-1][1])
            # 变化间隔统计
            ct = [ts[k][0] for k in range(1, len(ts)) if ts[k][1] != ts[k-1][1]]
            mgap = max([ct[k+1]-ct[k] for k in range(len(ct)-1)], default=0.0)
            line.append(f'{band}: {len(ts)}帧/{span:.1f}s = {len(ts)/max(span,1e-9):.1f}Hz报文, '
                        f'变化{chg}次 = {chg/max(span,1e-9):.2f}次/s, 最长不变{mgap:.1f}s')
        print(f'  seg{segno}: ' + ' | '.join(line))
        for band in ('moving', 'low', 'standstill'):
            ts = band_ts[band]
            if len(ts) < 30: continue
            span = ts[-1][0] - ts[0][0]
            chg = sum(1 for k in range(1, len(ts)) if ts[k][1] != ts[k-1][1])
            d = tot[band]; d['frames'] += len(ts); d['span'] += span; d['chg'] += chg
    print(f'--- {pref} 汇总 ---')
    for band, d in tot.items():
        if d['span'] <= 0: continue
        print(f'  {band:11s}: 报文 {d["frames"]/d["span"]:5.1f} Hz | idx变化 {d["chg"]/d["span"]:5.2f} 次/s')
