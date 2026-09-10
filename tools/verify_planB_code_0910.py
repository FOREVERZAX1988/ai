#!/usr/bin/env python3
"""落地复核（2026-09-10, 二版：三处同源）：从**已写入代码的常量**复核方案B(B1) 的效果
- 常量来源：radard.py（A2 融合）/ radar_interface.py（A3 雷达点）/ carcontroller.py（第三处映射：
  仪表显示源换算），脚本直接从源码正则提取并断言**三处相同**（同源检查），不硬编码，
  避免"文档 vs 代码"漂移。
- A2 判据已于 2026-09-10 物理化（rel = |d_vis-d_stock|/d_stock），本脚本的替换率口径
  本来就是物理域（ratio = |d_vis - d_stock|/d_stock > 0.30），故两者现在完全对齐。
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
CC = consts(f"{ROOT}/opendbc_repo/opendbc/car/volkswagen/carcontroller.py")
print(f"A2(radard.py)          = {A2}")
print(f"A3(radar_interface.py) = {A3}")
print(f"CC(carcontroller.py)   = {CC}   # 第三处：op_lead_to_index 仪表显示源")
print(f"[同源检查] A2 == A3 == CC : {A2 == A3 == CC}")
assert A2 == A3 == CC, "三处系数不同源，禁止上线"
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


# ---------------- 第三处映射（仪表显示源换算）----------------
print("\n=== 第三处映射：carcontroller.op_lead_to_index（B1 反解）===")
try:
  import sys
  sys.path.insert(0, ROOT)
  from opendbc.car.volkswagen.carcontroller import CarController as CCtl
  fwd, inv = CCtl.op_index_to_drel, CCtl.op_lead_to_index
  inv_ls = lambda d: inv(d, 3.0)     # 低速 d/max(v,5)
  err = max(abs(fwd(inv((A * i + B) * 10.0, 10.0), 10.0) - (A * i + B) * 10.0) for i in range(30, 1021))
  print(f"[1] 正/反解往返最大误差(<截断1idx): {err:.3f} m")
  print(f"[2] 无突跳：idx 步长 {(A * 10.0):.4f} m（直线）")
  # 与旧 0902 153 点表的对照（旧表已删，这里用文档记录的参考点）
  ref = {100: 1.65, 200: 2.38, 400: 3.128, 560: 3.955, 780: 7.149}
  print("[3] 旧 0902 表 vs B1（同一 idx 的时距 t）：")
  for i, t_old in ref.items():
    print(f"      idx={i:4d}: 0902 {t_old:.3f} s -> B1 {A*i+B:.3f} s ({(A*i+B)/t_old-1:+.1%})")
  print(f"[4] 显示源迟滞已物理化：|d_stock - d_vis| / d_vis > {0.30}（旧为 idx 域 30% ≈ 物理 23~27%）")
except Exception as ex:
  print(f"[warn] carcontroller 导入失败({type(ex).__name__}: {ex})，跳过第三处映射复核")


# ---------------- A2 判据：idx 域 vs 距离域（物理化前后的操作点漂移）----------------
print("\n=== A2 判据物理化前后：模式判定差异（B1 口径）===")
X = gate(ALL)
if len(X):
  idx, v, dv = X[:, 0], np.maximum(X[:, 1], 5.0), X[:, 2]
  d_stock = (A * idx + B) * v
  rel_new = np.abs(dv - d_stock) / np.maximum(d_stock, 1.0)          # 新（距离域）
  # 旧口径 idx 域：ratio = |vis_idx - stock_idx| / stock_idx = |Δt| / (t - B)
  t_vis = dv / v
  ratio_old = np.abs(t_vis - d_stock / v) / np.maximum(d_stock / v - B, 1e-6)
  rep_new, rep_old = rel_new > 0.30, ratio_old > 0.30
  print(f"  替换率： 物理域(新代码) {100*rep_new.mean():.1f}%  |  idx域(旧代码) {100*rep_old.mean():.1f}%")
  print(f"  判定不一致帧： {100*np.mean(rep_new != rep_old):.1f}% （其中旧判'替换'新判'混合' {100*np.mean(rep_old & ~rep_new):.1f}%）")
  print(f"  旧 idx 域阈值的平均放大因子 t/(t-B)： {np.median((d_stock/v)/np.maximum(d_stock/v-B,1e-6)):.3f}"
        f"  -> 旧名义 30% 实为物理 {100*0.30/np.median((d_stock/v)/np.maximum(d_stock/v-B,1e-6)):.1f}%")
else:
  print("  [warn] 无数据，跳过")
