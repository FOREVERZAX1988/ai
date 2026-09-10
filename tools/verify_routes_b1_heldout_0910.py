#!/usr/bin/env python3
"""路试验收扫描（2026-09-10 会话五）：检验 B1 标定的准确性（独立口径，不复述文档）。

新增三件事（相对 verify_planB_code_0910.py）：
  [1] 留一路线交叉验证 LORO：每次用 5 条 route 拟合 (a,b)，在第 6 条上测 —— 给"泛化精度"而非样本内精度
  [2] 无门控全量扫描：不加 |v_vis-v_can|<=0.5 / 100<=idx<=560 —— 看真车全工况下的距离差
  [3] 分速度段 / 分距离段残差：查 B1 有无系统性尺度倾斜（分段正负是否交替）
常量一律从源码正则提取（A2/A3/CC 三处必须同源），不硬编码。
用法: cd /data/openpilot && python3 ai/tools/verify_routes_b1_heldout_0910.py
"""
import re, json
import numpy as np

ROOT = "/data/openpilot"
OLD = ['00000002', '00000003', '00000004', '00000049']
NEW = ['00000071', '00000072']
ROUTES = OLD + NEW

def consts(path):
  s = open(path, encoding="utf-8").read()
  return (float(re.search(r"MACAN_B1_T_A = ([\d.]+)", s).group(1)),
          float(re.search(r"MACAN_B1_T_B = ([\d.]+)", s).group(1)))

A2 = consts(f"{ROOT}/openpilot/selfdrive/controls/radard.py")
A3 = consts(f"{ROOT}/opendbc_repo/opendbc/car/volkswagen/radar_interface.py")
CC = consts(f"{ROOT}/opendbc_repo/opendbc/car/volkswagen/carcontroller.py")
assert A2 == A3 == CC, f"三处系数不同源 {A2} {A3} {CC}"
A, B = A2
OLD153 = (0.008951, 0.1625)
NEWCODE = (0.008718, 1.0178)
print(f"[同源检查] A2==A3==CC = {A2}  (B1 现行代码)")

R = {}
for r in ROUTES:
  try:
    R[r] = np.load(f"/tmp/rows_{r}.npy")
  except FileNotFoundError:
    R[r] = np.zeros((0, 8))
for r in ROUTES:
  print(f"  {r} 帧(缓存 stride=3) = {len(R[r])}")

def cols(X):
  return X[:, 0], np.maximum(X[:, 1], 5.0), X[:, 2], X[:, 3], X[:, 4]

def gate(X, dt=0.5, ilo=100, ihi=560, vlo=8.0):
  idx, v, dv, vv, vc = cols(X)
  return X[(v >= vlo) & (np.abs(vv - vc) <= dt) & (idx >= ilo) & (idx <= ihi) & (dv > 0)]

def gate_full(X):
  idx, v, dv, vv, vc = cols(X)
  return X[(idx >= 1) & (idx <= 1020) & (dv > 0) & (X[:, 1] > 0)]

def d_of(X, ab):
  a, b = ab
  return (a * X[:, 0] + b) * np.maximum(X[:, 1], 5.0)

def met(X, ab):
  if not len(X):
    return None
  d = d_of(X, ab); dv = X[:, 2]; e = dv - d
  return dict(n=len(X), med=float(np.median(e)), mad=float(np.median(np.abs(e))),
              p5=float(100 * np.mean(np.abs(e) <= 5)),
              r30=float(100 * np.mean(np.abs(e) / np.maximum(d, 1.0) > 0.30)),
              p90=float(np.percentile(np.abs(e), 90)))

def fit(X, kind='l1'):
  """最小化距离域 med|Δ|(kind='med') / mean|Δ|(l1) / P84(kind='p84')；返回 (a,b)"""
  dvv = X[:, 2]
  idx, v = X[:, 0], np.maximum(X[:, 1], 5.0)
  s, _, _, _ = np.linalg.lstsq(np.vstack([idx, np.ones_like(idx)]).T, dvv / v, rcond=None)
  p = np.array([float(s[0]), float(s[1])])
  def obj(q):
    ad = np.abs(dvv - (q[0] * idx + q[1]) * v)
    return {'med': np.median(ad), 'l1': np.mean(ad), 'p84': np.percentile(ad, 84)}[kind]
  f = obj(p); step = np.array([2e-4, 0.20])
  for _ in range(300):
    imp = False
    for k in range(2):
      for sg in (+1, -1):
        q = p.copy(); q[k] += sg * step[k]
        if q[0] <= 0: continue
        fq = obj(q)
        if fq < f - 1e-12: p, f, imp = q, fq, True
    if not imp:
      step *= 0.5
      if step[0] < 1e-9: break
  return float(p[0]), float(p[1])

G = {r: gate(R[r]) for r in ROUTES}
GALL = np.vstack([G[r] for r in ROUTES if len(G[r])])
FO = {r: gate_full(R[r]) for r in ROUTES}
FALL = np.vstack([FO[r] for r in ROUTES if len(FO[r])])

print("\n" + "=" * 78)
print("【1】现行 B1 逐 route（门控干净集 vs 无门控全量）")
print("  口径: med(视觉-雷达) / med|Δ| / ≤5m% / A2替换率(>30%)")
print(f"  {'route':8s} {'n门控':>6s} {'B1(gated)':>34s} {'n全量':>7s} {'B1(全量)':>34s}")
for r in ROUTES:
  mg, mf = met(G[r], (A, B)), met(FO[r], (A, B))
  sg = f"{mg['med']:+6.2f} / {mg['mad']:5.2f} / {mg['p5']:5.1f}% / {mg['r30']:4.1f}%" if mg else "-"
  sf = f"{mf['med']:+6.2f} / {mf['mad']:5.2f} / {mf['p5']:5.1f}% / {mf['r30']:4.1f}%" if mf else "-"
  print(f"  {r[-5:]:8s} {(mg['n'] if mg else 0):6d} {sg:>34s} {(mf['n'] if mf else 0):7d} {sf:>34s}")
for tag, X in (("池化 gated", GALL), ("池化 全量", FALL)):
  for name, ab in (("old153", OLD153), ("newcode", NEWCODE), ("B1(代码)", (A, B))):
    m = met(X, ab)
    print(f"  {tag:11s} {name:9s} n={m['n']:7d} med={m['med']:+6.2f} med|Δ|={m['mad']:5.2f} "
          f"≤5m={m['p5']:5.1f}% r30={m['r30']:4.1f}% P90|Δ|={m['p90']:6.2f}")

print("\n" + "=" * 78)
print("【2】留一路线交叉验证 LORO（拟合集合不含被测路线 → 泛化精度）")
print(f"  {'holdout':8s} {'拟合a':>9s} {'拟合b':>7s} | {'med':>7s} {'med|Δ|':>7s} {'≤5m%':>6s} {'r30%':>5s}")
l1, p84, meds = [], [], []
for r in ROUTES:
  tr = np.vstack([G[q] for q in ROUTES if q != r and len(G[q])])
  for kind, store in (('l1', l1), ('p84', p84), ('med', meds)):
    a, b = fit(tr, kind)
    m = met(G[r], (a, b))
    store.append((r, a, b, m['med'], m['mad'], m['p5'], m['r30']))
for store, nm in ((l1, 'L1  (mean|Δ|)'), (p84, 'P84'), (meds, 'med(|Δ|)')):
  print(f"  --- 拟合目标 {nm} ---")
  for r, a, b, md, mad, p5, r30 in store:
    print(f"  {r[-5:]:8s} {a:9.6f} {b:+7.3f} | {md:+7.2f} {mad:7.2f} {p5:6.1f} {r30:5.1f}")
  print(f"  >>> 泛化汇总: med|Δ| 中位={np.median([s[4] for s in store]):.2f}m  ≤5m 均值={np.mean([s[5] for s in store]):.1f}%  "
        f"最差 med|Δ|={max(s[4] for s in store):.2f}m")

print("\n" + "=" * 78)
print("【3】跨分支泛化（不是同分支自证）")
PD = gate(np.vstack([R[r] for r in OLD]))
PN = gate(np.vstack([R[r] for r in NEW]))
ao, bo = fit(PD, 'l1'); an, bn = fit(PN, 'l1')
print(f"  旧分支拟合: a={ao:.6f} b={bo:+.3f}   新分支拟合: a={an:.6f} b={bn:+.3f}")
for nm, ab in (("旧分支拟合→测新分支", (ao, bo)), ("新分支拟合→测旧分支", (an, bn))):
  m = met(PN if '新分支' in nm.split('→')[1] else PD, ab)
  print(f"  {nm}: med={m['med']:+6.2f} med|Δ|={m['mad']:5.2f} ≤5m={m['p5']:5.1f}% r30={m['r30']:4.1f}%")

print("\n" + "=" * 78)
print("【4】B1 残差分速度段 / 分距离段（查系统性倾斜；正负应交替）")
idx, v, dv, vv, vc = cols(GALL)
d = d_of(GALL, (A, B)); e = dv - d
print("  速度段 (m/s):")
print("   段         n     med(vis-rad)  med|Δ|  rel-med")
for lo, hi in [(8, 10), (10, 14), (14, 18), (18, 24), (24, 40)]:
  s = (v >= lo) & (v < hi)
  if s.sum() > 30:
    print(f"   {lo:2d}-{hi:<2d} {s.sum():7d}   {np.median(e[s]):+8.2f}   {np.median(np.abs(e[s])):6.2f}  "
          f"{100*np.median(e[s]/np.maximum(d[s],1)):+6.1f}%")
print("  距离段 (m) —— 视觉距离:")
print("   段         n     med(vis)   med(rad)  Δmed    相对")
for lo, hi in [(0, 15), (15, 25), (25, 40), (40, 60), (60, 90), (90, 1e9)]:
  s = (dv >= lo) & (dv < hi)
  if s.sum() > 30:
    print(f"   {lo:3.0f}-{hi if hi < 1e9 else -1:3.0f} {s.sum():8d}   {np.median(dv[s]):6.1f}   {np.median(d[s]):6.1f}  "
          f"{np.median(dv[s]-d[s]):+6.2f}  {100*(np.median(dv[s]-d[s]))/max(np.median(dv[s]),1):+5.1f}%")

json.dump({"B1": [A, B], "old153": list(OLD153), "newcode": list(NEWCODE),
           "loro_l1": l1, "loro_p84": p84, "loro_med": meds,
           "cross": {"old_fit": [ao, bo], "new_fit": [an, bn]}},
          open("/tmp/verify_routes_b1_heldout.json", "w"), indent=1)
print("\nDONE -> /tmp/verify_routes_b1_heldout.json")
