#!/usr/bin/env python3
"""0910 多route复核 v2：运动学闭合(K1)按 |Δv_ego| 分层。
关键动机：常数时距偏置 δ 对 Δd 的贡献 = δ*(v1-v0) —— 恒速窗口完全看不见它。
所以只有 |Δv_ego| 大的窗口才能判定 "+0.8s" 到底存不存在。
用法: python3 xval_closure_dv_0910.py <seg> [seg...]
"""
import sys, os, importlib.util
import numpy as np
spec = importlib.util.spec_from_file_location("vf", "/data/openpilot/ai/tools/verify_formula_independent_0910.py")
vf = importlib.util.module_from_spec(spec); spec.loader.exec_module(vf)

def closure2(rows, L=2.0, min_abs_ds=1.0):
    out = []
    for i, j in vf.windows(rows, L):
        t0, idx0, v0, vl0, vd0, vv0, vp0 = rows[i]
        t1, idx1, v1, vl1, vd1, vv1, vp1 = rows[j]
        if t1 - t0 < 0.8 * L or idx0 <= 10 or idx1 <= 10: continue
        ds = 0.0; ok = True
        for k in range(i, j):
            rk, rk1 = rows[k], rows[k+1]
            if rk[3] is None or rk1[3] is None or rk[1] <= 10 or rk1[1] <= 10: ok = False; break
            if abs(rk1[1]-rk[1]) > 25 or abs(idx1-idx0) > 160: ok = False; break
            if abs(rk1[3]-rk[3]) > 1.5: ok = False; break
            ds += 0.5*((rk[3]-rk[2]) + (rk1[3]-rk1[2]))*(rk1[0]-rk[0])
        if not ok or abs(ds) < min_abs_ds: continue
        dv = v1 - v0
        out.append((ds, vf.t_old(idx1)*v1 - vf.t_old(idx0)*v0,
                    vf.t_new(idx1)*v1 - vf.t_new(idx0)*v0,
                    (idx0+idx1)/2.0, dv,
                    (vd1-vd0) if (vd0 is not None and vd1 is not None) else np.nan))
    return out

def rep(tag, a, ds, yo, yn, dv, ib):
    if len(a) < 30: print(f'  {tag:<22} 样本不足 n={len(a)}'); return
    ro, rn = yo/ds, yn/ds
    print(f'  {tag:<22} n={len(a):>5}  median|ds|={np.median(np.abs(ds)):5.1f}m  '
          f'ratio: 旧={np.median(ro):.3f} 新={np.median(rn):.3f} | '
          f'median|res|: 旧={np.median(np.abs(yo-ds)):.2f}m 新={np.median(np.abs(yn-ds)):.2f}m')

if __name__ == '__main__':
    specs = sys.argv[1:]
    allrows = []
    for spec in specs:
        f = f'/data/media/0/realdata/{spec}/rlog.zst'
        if os.path.exists(f):
            allrows.extend(vf.parse(f))
    print(f'总行数={len(allrows)}')
    C = closure2(allrows)
    ds = np.array([c[0] for c in C]); yo = np.array([c[1] for c in C])
    yn = np.array([c[2] for c in C]); ib = np.array([c[3] for c in C])
    dv = np.array([c[4] for c in C]); yv = np.array([c[5] for c in C])
    print('\n=== A. 全体 ==='); rep('ALL', ds, ds, yo, yn, dv, ib)
    print('\n=== B. 按 |Δv_ego| 分层（唯一能看出常数时距偏置的维度）===')
    for lo, hi in [(0,1),(1,3),(3,99)]:
        m = (np.abs(dv) >= lo) & (np.abs(dv) < hi)
        rep(f'|dv| {lo}-{hi} m/s', ds[m], ds[m], yo[m], yn[m], dv[m], ib[m])
    print('\n=== C. 按 |Δs| 分层（强相对运动窗口）===')
    for lo, hi in [(1,3),(3,8),(8,99)]:
        m = (np.abs(ds) >= lo) & (np.abs(ds) < hi)
        rep(f'|ds| {lo}-{hi} m', ds[m], ds[m], yo[m], yn[m], dv[m], ib[m])
    print('\n=== D. |Δv|>3 且 |Δs|>8 的“硬核”窗口 ===')
    m = (np.abs(dv) > 3) & (np.abs(ds) > 8)
    rep('dv>3 & ds>8', ds[m], ds[m], yo[m], yn[m], dv[m], ib[m])
    print('\n=== E. 近端 idx<100（新公式 0.8s 平锚处）===')
    m = ib < 100
    rep('idx<100', ds[m], ds[m], yo[m], yn[m], dv[m], ib[m])
    print('\n=== F. K2 视觉自洽闭合（对照：几乎恒等，只验证视觉内部自洽）===')
    mv = ~np.isnan(yv)
    rep('视觉 d_vis', ds[mv], ds[mv], yv[mv], yv[mv], dv[mv], ib[mv])
