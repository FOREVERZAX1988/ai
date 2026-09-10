#!/usr/bin/env python3
"""0910 池化复核：5 routes (0002/0049/0071/0072/0004) 合并
 (1) K1 运动学闭合，按 |Δv_ego| / idx 分层
 (2) 非参数反解 τ(idx)，与 旧153表 / 新线性公式 对比
"""
import os, importlib.util
import numpy as np
def load(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
vf = load("vf", "/data/openpilot/ai/tools/verify_formula_independent_0910.py")
xd = load("xd", "/data/openpilot/ai/tools/xval_closure_dv_0910.py")
ft = load("ft", "/data/openpilot/ai/tools/fit_tau_nonparam_0910.py")

routes = ["00000002--5284e8b7f1","00000049--ac8e2bc7b1","00000071--363798636e","00000072--d7b307b456","00000004--915ebf086f"]
segs = []
for p in routes:
    segs += [os.path.basename(d.rstrip('/')) for d in os.popen(f'ls -d /data/media/0/realdata/{p}--*/').read().split()]
rows = []
for s in segs:
    f = f'/data/media/0/realdata/{s}/rlog.zst'
    if os.path.exists(f): rows.extend(vf.parse(f))
print(f'池化总行数={len(rows)}  segments={len(segs)}')

C = xd.closure2(rows)
ds = np.array([c[0] for c in C]); yo = np.array([c[1] for c in C]); yn = np.array([c[2] for c in C])
ib = np.array([c[3] for c in C]); dv = np.array([c[4] for c in C]); yv = np.array([c[5] for c in C])
print('\n### 池化 A. 全体'); xd.rep('ALL', ds, ds, yo, yn, dv, ib)
print('\n### 池化 B. 按 |dv_ego| 分层（常数时距偏置唯一可见的维度）')
for lo, hi in [(0,1),(1,3),(3,99)]:
    m = (np.abs(dv) >= lo) & (np.abs(dv) < hi); xd.rep(f'|dv| {lo}-{hi} m/s', ds[m], ds[m], yo[m], yn[m], dv[m], ib[m])
print('\n### 池化 C. 按 idx 分层')
for lo, hi in [(27,100),(100,200),(200,300),(300,400),(400,561),(561,1021)]:
    m = (ib >= lo) & (ib < hi); xd.rep(f'idx {lo}-{hi}', ds[m], ds[m], yo[m], yn[m], dv[m], ib[m])
print('\n### 池化 D. |dv| 分层 且 idx>=100（排除近端平锚区）')
for lo, hi in [(0,1),(1,3),(3,99)]:
    m = (np.abs(dv) >= lo) & (np.abs(dv) < hi) & (ib >= 100); xd.rep(f'|dv| {lo}-{hi} & idx>=100', ds[m], ds[m], yo[m], yn[m], dv[m], ib[m])
print('\n### 池化 F. K2 视觉自洽（对照）')
mv = ~np.isnan(yv); xd.rep('视觉 d_vis', ds[mv], ds[mv], yv[mv], yv[mv], dv[mv], ib[mv])

# ---------- 非参数反解 τ(idx) ----------
W = ft.build(rows, min_abs_ds=1.0, vmin=5.5)
print(f'\n=== 非参数反解 τ(idx): 方程数 n={len(W)} ===')
G = np.arange(20, 1041, 20.0); ng = len(G)
def binof(idx):
    return np.clip(((idx - 20) / 20.0).round().astype(int), 0, ng-1)
A = np.zeros((len(W), ng)); y = np.zeros(len(W))
for r, (i0, i1, v0, v1, d) in enumerate(W):
    A[r, binof(i1)] += v1; A[r, binof(i0)] -= v0; y[r] = d
D = np.zeros((ng-2, ng))
for k in range(ng-2): D[k, k], D[k, k+1], D[k, k+2] = 1.0, -2.0, 1.0
lam = 30.0
tau = np.linalg.solve(A.T@A + lam*(D.T@D), A.T@y)
res = A@tau - y
print(f'拟合残差 median|.|={np.median(np.abs(res)):.2f}m rmse={np.sqrt(np.mean(res**2)):.2f}m  (|ds|中位 {np.median(np.abs(y)):.1f}m)')
print('\n idx  反解τ   旧表τ   新式τ  | 反解-旧  反解-新   bin权重')
for g, b in zip(G, range(ng)):
    w = np.abs(A[:, b]).sum()
    if w < 100: continue
    to, tn = vf.t_old(g), vf.t_new(g)
    print(f'{g:5.0f} {tau[b]:6.3f} {to:6.3f} {tn:6.3f}  | {tau[b]-to:+6.3f} {tau[b]-tn:+6.3f}  {w:8.0f}')
m = (G >= 100) & (G <= 560)
c1 = np.polyfit(G[m], tau[m], 1); r1 = tau[m]-np.polyval(c1, G[m])
c2 = np.polyfit(G[m], tau[m], 2); r2 = tau[m]-np.polyval(c2, G[m])
print(f'\n反解τ(100-560) 单直线: slope={c1[0]:.6f} int={c1[1]:+.3f} max|res|={np.max(np.abs(r1)):.3f}s rms={np.sqrt(np.mean(r1**2)):.3f}s')
print(f'反解τ(100-560) 二次  : max|res|={np.max(np.abs(r2)):.3f}s rms={np.sqrt(np.mean(r2**2)):.3f}s')
print(f'旧表(100-560) 单直线: slope=0.008951 int=+0.1625 R2=0.99335 max|res|=0.38s  (0910 crosscheck记录)')
print(f'新公式(100-560) 单直线: slope=0.008718 int=+1.0178 (定义即直线)')
