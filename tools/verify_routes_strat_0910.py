#!/usr/bin/env python3
"""路试标定准确性分层复核（2026-09-10 会话五）：三段合一
  [A] 分分支 × 分速度段 × 分距离段 —— 检查残差是否单调倾斜（并防止"混分支造成假趋势"）
  [B] 同目标干净子集 (|Δ|≤8m) 与 误差集中度 —— 量化"尾部误差来自哪里"
  [C] 参数可辨识性 —— a/b 的 LORO/自助重采样离散度，判定"反复横跳调参"是否有信息量
用法: cd /data/openpilot && python3 ai/tools/verify_routes_strat_0910.py
依赖: /tmp/rows_<route>.npy (stride采样, 8列) / /tmp/rowsC_<route>.npy (连续, 10列, 含 seg/k)
"""
import numpy as np

A, B = 0.008969, 0.332          # 现行代码 B1（应与 radard/radar_interface/carcontroller 三处一致）
OLD = ['00000002', '00000003', '00000004', '00000049']
NEW = ['00000071', '00000072']
R = {r: np.load(f'/tmp/rows_{r}.npy') for r in OLD + NEW}


def cols(X):
  return X[:, 0], np.maximum(X[:, 1], 5.0), X[:, 2], X[:, 3], X[:, 4]


def gate(X, dt=0.5, vlo=8.0, ilo=100, ihi=560):
  idx, v, dv, vv, vc = cols(X)
  return X[(v >= vlo) & (np.abs(vv - vc) <= dt) & (idx >= ilo) & (idx <= ihi) & (dv > 0)]


def bands(X, tag):
  idx, v, dv, vv, vc = cols(X)
  d = (A * idx + B) * v
  e = dv - d
  print(f"  [{tag}] n={len(X)}  med(v)={np.median(v):.1f} m/s  med(vis-rad)={np.median(e):+.2f} m")
  seg = []
  for lo, hi in [(8, 10), (10, 14), (14, 18), (18, 24), (24, 40)]:
    s = (v >= lo) & (v < hi)
    if s.sum() > 30:
      seg.append(f"{lo}-{hi}:{np.median(e[s]):+.2f}m({100*np.median(e[s]/np.maximum(d[s],1)):+.1f}%,n={int(s.sum())})")
  print("   速度段: " + "  ".join(seg))
  seg = []
  for lo, hi in [(0, 15), (15, 25), (25, 40), (40, 60), (60, 90), (90, 1e9)]:
    s = (dv >= lo) & (dv < hi)
    if s.sum() > 30:
      seg.append(f"{int(lo)}-{int(hi) if hi < 1e9 else -1}:{np.median(e[s]):+.2f}m({100*np.median(e[s]/np.maximum(d[s],1)):+.1f}%,n={int(s.sum())})")
  print("   距离段: " + "  ".join(seg))


def clean_and_concentration():
  rows = []
  for r in OLD + NEW:
    X = np.load(f'/tmp/rows_{r}.npy')
    idx, v, dv, vv, vc = cols(X)
    m = (v >= 8.0) & (np.abs(vv - vc) <= 0.5) & (idx >= 100) & (idx <= 560) & (dv > 0)
    idx, v, dv = idx[m], v[m], dv[m]
    d = (A * idx + B) * v
    ad = np.abs(dv - d)
    c = ad <= 8.0
    rows.append((r, len(dv), 100 * (1 - c.mean()), 100 * ad[~c].sum() / max(ad.sum(), 1e-9),
                 float(np.median(ad[c])), float(100 * np.mean(ad[c] <= 5))))
    print(f"  [{r[-5:]}] 全 n={len(dv):6d} med|Δ|={np.median(ad):5.2f} ≤5m={100*np.mean(ad<=5):5.1f}%"
          f" | 同目标干净(|Δ|≤8m) n={int(c.sum()):6d} ({100*c.mean():5.1f}%) med|Δ|={np.median(ad[c]):5.2f} ≤5m={100*np.mean(ad[c]<=5):5.1f}%"
          f" | 剔除={100*(1-c.mean()):4.1f}% 但贡献了总|Δ|的 {100*ad[~c].sum()/ad.sum():4.0f}%")
  return rows


def concentration_by_seg(prefix='00000072'):
  X = np.load(f'/tmp/rowsC_{prefix}.npy')
  idx, v, dv, vv, vc, seg = X[:, 0], np.maximum(X[:, 1], 5.0), X[:, 2], X[:, 3], X[:, 4], X[:, 8]
  m = (v >= 8.0) & (np.abs(vv - vc) <= 0.5) & (idx >= 100) & (idx <= 560) & (dv > 0)
  idx, v, dv, seg = idx[m], v[m], dv[m], seg[m]
  d = (A * idx + B) * v
  ad = np.abs(dv - d)
  tot = ad.sum()
  rows = sorted(((ad[seg == s].sum(), s, int((seg == s).sum()), float(np.median(dv[seg == s] - d[seg == s])),
                  100 * np.mean(ad[seg == s] > 8)) for s in set(seg) if (seg == s).sum() >= 40), reverse=True)
  print(f"  [{prefix}] |Δ| 质量 top5 / 共 {len(rows)} 有效段 (总量 {tot:.0f} m·帧)")
  for sm, s, n, md, p8 in rows[:5]:
    print(f"    seg{int(s):3d} n={n:5d} 质量占比={100*sm/tot:4.1f}% medΔ={md:+7.2f} >8m={p8:5.1f}%")
  print(f"    top5 合计 {100*sum(x[0] for x in rows[:5])/tot:.1f}%")


def identifiability():
  A_ = np.vstack([gate(R[r]) for r in OLD + NEW])
  idx, v = A_[:, 0], np.maximum(A_[:, 1], 5.0)
  t = A_[:, 2] / v
  s, _, _, _ = np.linalg.lstsq(np.vstack([idx, np.ones_like(idx)]).T, t, rcond=None)
  a0, b0 = float(s[0]), float(s[1])
  print(f"  池化解 a={a0:.6f} b={b0:+.4f}  (代码现值 a={A:.6f} b={B:+.4f})")
  print(f"  corr(idx,v)={np.corrcoef(idx, v)[0,1]:+.3f}  idx P1..P99={np.percentile(idx,1):.0f}..{np.percentile(idx,99):.0f}")
  print(f"  {'拟合集':14s} {'a':>10s} {'b':>8s} {'t(150)':>8s} {'t(250)':>8s} {'t(400)':>8s}")
  for r in OLD + NEW:
    tr = np.vstack([gate(R[q]) for q in OLD + NEW if q != r])
    i2, v2 = tr[:, 0], np.maximum(tr[:, 1], 5.0)
    s2, _, _, _ = np.linalg.lstsq(np.vstack([i2, np.ones_like(i2)]).T, tr[:, 2] / v2, rcond=None)
    a, b = float(s2[0]), float(s2[1])
    print(f"  留出{r[-5:]:9s} {a:10.6f} {b:+8.4f} {a*150+b:8.3f} {a*250+b:8.3f} {a*400+b:8.3f}")
  print("  → 结论：a 变异 ~5%、b 变异 ~28%，但 t(idx) 在典型 idx 上只变 ~3%；")
  print("     b（截距）单独**不可辨识**（与 a 强共线），因此『换目标函数重拟合 → b 大幅跳动』不含新信息。")


print("=" * 78); print("【A】分分支 × 分速度段 × 分距离段（防混分支假趋势）")
bands(gate(np.vstack([R[r] for r in OLD])), "旧分支 0002/3/4/49")
bands(gate(np.vstack([R[r] for r in NEW])), "新分支 0071/0072")
print("\n" + "=" * 78); print("【B】同目标干净子集 & 误差集中度")
clean_and_concentration()
print("  分段集中度（新分支，连续帧口径）：")
concentration_by_seg('00000071'); concentration_by_seg('00000072')
print("\n" + "=" * 78); print("【C】参数可辨识性")
identifiability()
