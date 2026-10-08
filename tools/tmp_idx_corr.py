#!/usr/bin/env python3
"""idx 相关性与 zl 分层拟合（v 4-15 m/s，radar=0 视觉 lead，|vRel|<=0.3）。"""
import glob
import numpy as np

rows = []
for f in sorted(glob.glob('/data/openpilot/ai/tools/_trace_00000*.txt')):
    with open(f) as fh:
        next(fh)
        for ln in fh:
            p = ln.rstrip('\n').split('\t')
            if len(p) < 21:
                continue
            try:
                rows.append((float(p[2]), float(p[4]), int(p[5]), float(p[6]), float(p[7]),
                             float(p[10]), float(p[19])))
            except ValueError:
                continue
a = np.array(rows)
idx, vis, radar, dRel, vRel, v, zl = a.T
m = (idx >= 2) & (idx < 1021) & (v >= 4) & (v < 15) & (np.abs(vRel) <= 0.3) & (radar == 0) & (dRel > 1)
idx, vis, dRel, v, zl = idx[m], vis[m], dRel[m], v[m], zl[m]
t = dRel / v
print(f'样本 {len(idx)}   v∈[4,15) m/s')
print(f'corr(idx, v)      = {np.corrcoef(idx, v)[0,1]:+.3f}')
print(f'corr(idx, dRel)   = {np.corrcoef(idx, dRel)[0,1]:+.3f}')
print(f'corr(idx, t=d/v)  = {np.corrcoef(idx, t)[0,1]:+.3f}')
print(f'corr(idx^0.5, t)  = {np.corrcoef(np.sqrt(idx), t)[0,1]:+.3f}')
print(f'corr(log idx, t)  = {np.corrcoef(np.log(idx), t)[0,1]:+.3f}')
print('\n按 Zeitluecke(zl) 分层：')
for z in sorted(set(zl.tolist())):
    s = zl == z
    if s.sum() < 200:
        print(f'  zl={z:.0f}: n={int(s.sum())} 样本不足')
        continue
    sl, in_ = np.polyfit(idx[s], t[s], 1)
    rms = float(np.sqrt(np.mean((sl * idx[s] + in_ - t[s]) ** 2)))
    print(f'  zl={z:.0f}: n={int(s.sum()):>6}  t = {sl:.6f}*idx + {in_:.3f}  RMS={rms:.2f}s  '
          f'idx中位={np.median(idx[s]):.0f} 实测t中位={np.median(t[s]):.2f}s')
print('\n非线性对照（全样本）：')
for name, x in (('idx', idx), ('idx/30', idx / 30), ('B1 t', 0.008969 * idx + 0.332)):
    rms = float(np.sqrt(np.mean((x - t) ** 2)))
    print(f'  {name:<8} RMS(vs 视觉 t) = {rms:.3f} s   中位比值={np.median(t/np.maximum(x,1e-6)):.2f}')
