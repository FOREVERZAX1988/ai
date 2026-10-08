#!/usr/bin/env python3
"""低速区 idx<->车距 标定复核：t_implied = dRel/v 对 idx 分速度带回归。
数据：ai/tools/_trace_*.txt (tarce 脚本输出)。仅用 radar=0(视觉 lead，dRel=视觉-1.52m) 且 |vRel|<=0.3 的帧。
"""
import glob
import numpy as np

FILES = sorted(glob.glob('/data/openpilot/ai/tools/_trace_00000*.txt'))
rows = []  # (idx, v, dRel, vRel, radar, route)
for f in FILES:
    name = f.split('_trace_')[1][:8]
    with open(f) as fh:
        next(fh)
        for ln in fh:
            p = ln.rstrip('\n').split('\t')
            if len(p) < 21:
                continue
            try:
                idx = float(p[2]); vis = float(p[4]); radar = int(p[5]); dRel = float(p[6])
                vRel = float(p[7]); v = float(p[10])
            except ValueError:
                continue
            if 2 <= idx < 1021 and v > 0.5 and dRel > 0.5:
                rows.append((name, idx, v, dRel, vRel, radar))
a = np.array([[r[1], r[2], r[3], r[4], r[5]] for r in rows])
names = np.array([r[0] for r in rows])
print(f'总帧 {len(a)}')
A = 0.008969; B = 0.332
bands = [(0.5, 2), (2, 4), (4, 8), (8, 15), (15, 30), (30, 200)]
print(f"\n{'v带(m/s)':<12}{'n':>7}{'slope':>9}{'intercept':>11}{'RMS(s)':>8}   (t = slope*idx + intercept)")
for lo, hi in bands:
    m = (a[:, 1] >= lo) & (a[:, 1] < hi) & (np.abs(a[:, 3]) <= 0.3) & (a[:, 4] == 0)
    n = int(m.sum())
    if n < 50:
        print(f'{lo:>4}-{hi:<6}{n:>7}   样本不足')
        continue
    t = a[m, 2] / a[m, 1]
    idx = a[m, 0]
    slope, inter = np.polyfit(idx, t, 1)
    rms = float(np.sqrt(np.mean((slope * idx + inter - t) ** 2)))
    tv = A * idx + B
    print(f'{lo:>4}-{hi:<6}{n:>7}{slope:>9.6f}{inter:>11.3f}{rms:>8.2f}   '
          f'当前B1表在该带的 t 中位={np.median(tv):.2f}s，实测 t 中位={np.median(t):.2f}s，比值中位={np.median(t/tv):.2f}')

print('\n--- 静止(idx 冻结)时的 idx/30 假设检验 (radar=1, v<0.15, idx有效) ---')
m = (a[:, 1] < 0.15)
seen = {}
print(f"{'route':<10}{'idx':>6}{'idx/30':>9}{'t(idx)*5':>10}")
for r in rows:
    name, idx, v, dRel, vRel, radar = r
    if v < 0.15 and idx >= 1 and radar == 1:
        key = (name, int(idx))
        if key in seen:
            continue
        seen[key] = 1
        print(f'{name:<10}{int(idx):>6}{idx / 30:>9.2f}{(A * idx + B) * 5:>10.2f}')
