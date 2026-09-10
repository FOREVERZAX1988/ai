#!/usr/bin/env python3
"""落地复核（2026-09-10）：从**已写入代码的常量**复核方案B(B1) 的效果
- 常量来源：radard.py 的 MACAN_B1_T_A/B（A2）与 radar_interface.py 的 MACAN_B1_T_A/B（A3），
  脚本直接从源码正则提取并断言两处相同（同源检查），不硬编码，避免"文档 vs 代码"漂移。
- 数据：/tmp/rows_<route>.npy  [idx,v_use,d_vis,v_vis,v_can,zl,d_old,d_new]（dump_rows_bus2.py 落盘）
- 门控与拟合脚本一致：v>=8 m/s 且 |v_vis-v_can|<=0.5 m/s 且 100<=idx<=560
- 复现指标：med(视觉-雷达) / med|Δ| / <=5m 占比 / A2 原厂替换率(ratio>30%)
用法：cd /data/openpilot && python3 ai/tools/verify_planB_code_0910.py
"""
import re
import numpy as np

ROOT = "/data/openpilot"
OLD = ['00000002', '00000003', '00000004', '00000049']
NEW = ['00000071', '00000072']


def consts(path):
  s = open(path, encoding="utf-8").read()
  a = float(re.search(r"MACAN_B1_T_A = ([\d.]+)", s).group(1))
  b = float(re.search(r"MACAN_B1_T_B = ([\d.]+)", s).group(1))
  return a, b


A2 = consts(f"{ROOT}/openpilot/selfdrive/controls/radard.py")
A3 = consts(f"{ROOT}/opendbc_repo/opendbc/car/volkswagen/radar_interface.py")
print(f"A2(radard.py)          = {A2}")
print(f"A3(radar_interface.py) = {A3}")
print(f"[同源检查] A2 == A3 : {A2 == A3}")
assert A2 == A3, "A2/A3 系数不同源，禁止上线"
A, B = A2

R = {}
for r in OLD + NEW:
  try:
    R[r] = np.load(f"/tmp/rows_{r}.npy")
  except FileNotFoundError:
    R[r] = np.zeros((0, 8))
ALL = np.vstack([R[r] for r in OLD + NEW])


def gate(X):
  idx, v, dv, vv, vc = X[:, 0], X[:, 1], X[:, 2], X[:, 3], X[:, 4]
  return X[(v >= 8.0) & (np.abs(vv - vc) <= 0.5) & (idx >= 100) & (idx <= 560) & (dv > 0)]


def d_of(a, b, X):
  return (a * X[:, 0] + b) * np.maximum(X[:, 1], 5.0)


def stats(tag, X):
  if not len(X):
    print(f"| {tag} | 0 | - | - | - | - |")
    return None
  dv = X[:, 2]
  out = {}
  for name, ds in (("old153", X[:, 6]), ("newcode", X[:, 7]), ("B1", d_of(A, B, X))):
    d = dv - ds
    ratio = np.abs(d) / np.maximum(ds, 1.0)
    out[name] = (float(np.median(d)), float(np.median(np.abs(d))), float((np.abs(d) <= 5).mean() * 100), float((ratio > 0.30).mean() * 100))
  row = f"| {tag} | {len(X)} | " + " | ".join(
    f"{out[n][0]:+.2f} / {out[n][1]:.2f} / {out[n][2]:.1f}% / {out[n][3]:.1f}%" for n in ("old153", "newcode", "B1")) + " |"
  print(row)
  return out


print("\n口径: med(视觉-雷达) / med|Δ| / <=5m 占比 / A2替换率(>30%)")
hdr = "| 集合 | n | old153 | newcode(旧代码) | **B1(新代码)** |"
print(hdr)
print("|---|---|---|---|---|")
pool = stats("池化 6 route", gate(ALL))
stats("旧分支 0002/3/4/49", gate(np.vstack([R[r] for r in OLD])))
stats("新分支 0071/0072", gate(np.vstack([R[r] for r in NEW])))
for r in OLD + NEW:
  stats(f"  {r[-5:]}", gate(R[r]))

print("\n[文档基线 MLB_MACAN_PLANB_FIT_0910.md] B1 池化: -0.77 / 1.90 / 82.0% / 6.3%")
if pool:
  print(f"[本次实测] B1 池化: {pool['B1'][0]:+.2f} / {pool['B1'][1]:.2f} / {pool['B1'][2]:.1f}% / {pool['B1'][3]:.1f}%")
  exp = (-0.77, 1.90, 82.0, 6.3)
  ok = all(abs(g - e) < 0.6 for g, e in zip(pool['B1'], exp))
  print(f"[一致性] 与文档基线相符: {ok}")
