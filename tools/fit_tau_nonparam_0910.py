#!/usr/bin/env python3
"""非参数反解原厂 idx->时距 τ(idx)：只用运动学恒等式，不假设任何函数形式。
每个滑动窗口给一条方程:  v1*τ(idx1) - v0*τ(idx0) = Δs = ∫(v_lead_can - v_ego)dt
=> 线性最小二乘(网格化 idx + 二阶差分平滑正则)。然后与旧153表/新线性公式对比。
用法: python3 fit_tau_nonparam_0910.py <seg> [seg...]
"""
import sys, os, importlib.util
import numpy as np
spec = importlib.util.spec_from_file_location("vf", "/data/openpilot/ai/tools/verify_formula_independent_0910.py")
vf = importlib.util.module_from_spec(spec); spec.loader.exec_module(vf)

def build(rows, L=2.0, min_abs_ds=1.0, vmin=5.5):
    W = []
    for i, j in vf.windows(rows, L):
        t0, idx0, v0 = rows[i][0], rows[i][1], rows[i][2]
        t1, idx1, v1 = rows[j][0], rows[j][1], rows[j][2]
        if t1-t0 < 0.8*L or idx0 <= 10 or idx1 <= 10: continue
        if v0 < vmin or v1 < vmin: continue
        ds = 0.0; ok = True
        for k in range(i, j):
            rk, rk1 = rows[k], rows[k+1]
            if rk[3] is None or rk1[3] is None or rk[1] <= 10 or rk1[1] <= 10: ok = False; break
            if abs(rk1[1]-rk[1]) > 25 or abs(idx1-idx0) > 160: ok = False; break
            if abs(rk1[3]-rk[3]) > 1.5: ok = False; break
            ds += 0.5*((rk[3]-rk[2]) + (rk1[3]-rk1[2]))*(rk1[0]-rk[0])
        if ok and abs(ds) >= min_abs_ds:
            W.append((idx0, idx1, v0, v1, ds))
    return W

if __name__ == '__main__':
    specs = sys.argv[1:]
    W = []
    for spec in specs:
        f = f'/data/media/0/realdata/{spec}/rlog.zst'
        if os.path.exists(f): W.extend(build(vf.parse(f)))
    print(f'方程数 n={len(W)}')
    G = np.arange(20, 1041, 20.0); ng = len(G)
    def binof(idx):
        b = np.clip(((idx - 20) / 20.0).round().astype(int), 0, ng-1)
        return b
    A = np.zeros((len(W), ng)); y = np.zeros(len(W))
    for r, (i0, i1, v0, v1, ds) in enumerate(W):
        A[r, binof(i1)] += v1; A[r, binof(i0)] -= v0; y[r] = ds
    D = np.zeros((ng-2, ng))
    for k in range(ng-2): D[k, k], D[k, k+1], D[k, k+2] = 1.0, -2.0, 1.0
    lam = 30.0
    tau = np.linalg.solve(A.T@A + lam*(D.T@D), A.T@y)
    res = A@tau - y
    print(f'拟合残差: median|.|={np.median(np.abs(res)):.2f}m  rmse={np.sqrt(np.mean(res**2)):.2f}m  (对比窗口 |ds| 中位 {np.median(np.abs(y)):.1f}m)')
    print('\n idx   反解τ   旧表τ   新式τ   |  反解-旧   反解-新   n(该bin方程权重)')
    for g, b in zip(G, range(ng)):
        w = np.abs(A[:, b]).sum()
        to, tn = vf.t_old(g), vf.t_new(g)
        if w < 50: continue
        print(f'{g:5.0f}  {tau[b]:6.3f}  {to:6.3f}  {tn:6.3f}   |  {tau[b]-to:+6.3f}   {tau[b]-tn:+6.3f}   {w:8.0f}')
    # 分段线性拟合指数：看反解 τ 与其单直线拟合的残差 => 是否有分段结构
    m = tau > 0
    c = np.polyfit(G[m], tau[m], 1)
    r1 = tau[m] - np.polyval(c, G[m])
    c2 = np.polyfit(G[m], tau[m], 2)
    r2 = tau[m] - np.polyval(c2, G[m])
    print(f'\n反解τ 单直线拟合: slope={c[0]:.6f} intercept={c[1]:.3f}  max|残差|={np.max(np.abs(r1)):.3f}s (rms {np.sqrt(np.mean(r1**2)):.3f})')
    print(f'反解τ 二次拟合  : max|残差|={np.max(np.abs(r2)):.3f}s (rms {np.sqrt(np.mean(r2**2)):.3f})')
    print(f'旧表在 idx100-560 单直线残差 max 0.38s -> 对比上面数字判断“原厂是否分段”')
