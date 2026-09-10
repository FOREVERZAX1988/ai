#!/usr/bin/env python3
"""独立标定: 用纯CAN运动学闭合反解 Abstandsindex -> 时距 t 的 (斜率a, 截距b)
真值: Delta s = Integral(v_lead_can - v_ego)dt      (只用 CAN 车速, 与视觉/公式无关)
模型: Delta d = a*(idx1*v1 - idx0*v0) + b*(v1 - v0)   [v>5m/s 段, 避开 max(v,5) 钳位]
  联立多窗口做最小二乘 -> 得到独立标定的 a,b; 与 旧153表 / 新线性公式 对比
另做: 跟停段绝对锚点 (closure 得到 d_start, 与公式预测对比)
"""
import sys, json, glob, os
import numpy as np
sys.path.insert(0, "/data/openpilot/ai/tools")
from macan_route_lib_0910 import parse_segment, t_old, t_new, REALDATA

def build(segs, L=5.0, step=0.5, min_ds=3.0, vmin=5.0, max_dv=1.5, max_idx_step=25):
    A = []  # dY/da  = idx1*v1 - idx0*v0
    B = []  # dY/db  = v1 - v0
    X = []  # truth Delta s
    IDX = []; VP = []; SEGI = []
    for si, seg in enumerate(segs):
        R = parse_segment(seg)
        if R is None: continue
        t, idx, v, vl = R["t"], R["idx"], R["v_wheel"], R["v_lead"]
        n = len(t); i = 0
        while i < n - 1:
            j = i
            while j < n - 1 and t[j] - t[i] < L: j += 1
            if t[j] - t[i] < 0.8 * L or not (t[j] - t[i] > 0): 
                lim = t[i] + step; i += 1
                while i < n - 1 and t[i] < lim: i += 1
                continue
            ok = idx[i] > 10 and idx[j] > 10 and v[i] > vmin and v[j] > vmin
            ds = 0.0
            if ok:
                for k in range(i, j):
                    s0, s1 = vl[k], vl[k + 1]
                    if not (np.isfinite(s0) and np.isfinite(s1)) or idx[k] <= 10 or idx[k + 1] <= 10 \
                       or abs(idx[k + 1] - idx[k]) > max_idx_step or abs(s1 - s0) > max_dv:
                        ok = False; break
                    ds += 0.5 * ((s0 - v[k]) + (s1 - v[k + 1])) * (t[k + 1] - t[k])
            if ok and abs(ds) >= min_ds and abs(idx[j] - idx[i]) <= 160:
                A.append(idx[j] * v[j] - idx[i] * v[i]); B.append(v[j] - v[i]); X.append(ds)
                IDX.append(0.5 * (idx[i] + idx[j])); VP.append(0.5 * (v[i] + v[j])); SEGI.append(si)
            lim = t[i] + step; i += 1
            while i < n - 1 and t[i] < lim: i += 1
    return (np.array(A), np.array(B), np.array(X), np.array(IDX), np.array(VP), np.array(SEGI))


def fit2(A, B, X, w=None):
    M = np.stack([A, B], 1)
    if w is None: w = np.ones(len(X))
    W = np.sqrt(w)[:, None]
    sol, *_ = np.linalg.lstsq(M * W, X * np.sqrt(w), rcond=None)
    res = M @ sol - X
    return sol, res


def rep(name, a, b, res, X, n):
    print(f"  {name:<22} a={a:.6f}  b={b:+.4f}   =>  t(100)={a*100+b:.2f}s t(300)={a*300+b:.2f}s t(560)={a*560+b:.2f}s")
    if res is not None:
        print(f"      n={n}  median|res|={np.median(np.abs(res)):.2f}m  rmse={np.sqrt(np.mean(res**2)):.2f}m  "
              f"median(res/|X|)={np.median(res/np.abs(X)):+.3f}  R2={1-np.sum(res**2)/np.sum((X-X.mean())**2):.3f}")


if __name__ == "__main__":
    pref = sys.argv[1] if len(sys.argv) > 1 else "00000002"
    L = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
    segs = [os.path.basename(d) for d in sorted(glob.glob(f"{REALDATA}/{pref}--*")) if os.path.exists(f"{d}/rlog.zst")]
    segs = [s for s in segs if os.path.exists(f"/data/openpilot/ai/tools/cache_0910/{s}.npz")] or segs
    print(f"route={pref} segs={len(segs)} L={L}s")
    A, B, X, IDX, VP, SEGI = build(segs, L=L)
    print(f"windows n={len(X)}  |Delta s| median={np.median(np.abs(X)):.1f}m  idx p05/p50/p95="
          f"{np.percentile(IDX,5):.0f}/{np.percentile(IDX,50):.0f}/{np.percentile(IDX,95):.0f}")
    if len(X) < 50:
        print("样本不足"); sys.exit(0)
    print("\n=== 独立最小二乘 (2参: a,b) ===")
    (a2, b2), res2 = fit2(A, B, X)
    rep("LS 2参数", a2, b2, res2, X, len(X))
    print("\n=== 对照 (固定斜率/截距) ===")
    res_old = np.array([t_old(i) * 1.0 for i in IDX])  # placeholder
    Yold = np.array([t_old(i) * 1.0 for i in [0]])     # noqa
    Xold = A * 0.008951 + 0  # 旧表线性段
    # 直接算旧表/新公式预测的 Delta d
    print("  (见下方固定口径残差)")
    pred_old = np.array([0.0]); 
    # 用 A,B 表达: t=a*idx+b 时 Delta d = A*a + B*b
    for nm, (a, b) in [("旧153表(线性拟合)", (0.008951, 0.1625)), ("新线性公式", (0.008718, 1.0178)),
                       ("LS(仅斜率,b=0)", (float(np.dot(A, X) / np.dot(A, A)), 0.0))]:
        pred = A * a + B * b
        res = pred - X
        rep(nm, a, b, res, X, len(X))
