#!/usr/bin/env python3
"""丰田式"视觉为主/雷达为辅"架构在本车数据上的可行性评估（2026-10-07，只读分析）。

目的：回答"是否可以照丰田的方式处理 Macan 的 视觉 vs 原厂 idx 关系"。
丰田口径（openpilot/selfdrive/controls/radard.py get_lead + match_vision_to_track）：
 - 视觉 lead 永远先算出来（leadsV3 -> get_RadarState_from_vision）；
 - 雷达 track 只有在"同目标 + 合理性门"通过时才顶替视觉：
     dist_sane: |d_radar - d_vis| < max(0.25*d_vis, 5.0)
     vel_sane : |vRel_rad + vEgo - v_vis| < 10  (或 v_ego+vRel_rad > 3)
 - 低速（v<4 m/s）额外允许"更近的静止雷达点"直接成为 lead（只有更近才接管）。
即：雷达**只能细化、或在低速把距离拉近（保守）**；绝不允许把距离改远、也绝不加权主导。

本脚本用本机 trace（列：seg T idx2 idx128 vis_dRel radar dRel vRel vLead aTgt vEgo ...）评估：
 A. 若照搬丰田门，冻结 idx 能不能被挡住（关键：5 m 绝对下限太松）
 B. 各速度带 d_rad vs d_vis 的偏差分布与"方向"（d_rad 更远 = 不安全方向）
 C. 现实现（A2 加权融合）与"视觉为主+低速取 min"相比，各自相对视觉的偏离
用法: python3 ai/tools/toyota_style_leads_eval_1007.py
"""
import glob
import numpy as np

A, B = 0.008969, 0.332          # B1: t(idx) = A*idx + B
FLOOR_V = 5.0                   # 现实现 max(v,5)
TOY_ABS = 5.0                   # 丰田 dist_sane 绝对项
TOY_REL = 0.25                  # 丰田 dist_sane 相对项
FILES = sorted(glob.glob('/data/openpilot/ai/tools/_trace_00000*.txt'))
COLS = ('seg', 'T', 'idx2', 'idx128', 'vis_dRel', 'radar', 'dRel', 'vRel', 'vLead', 'aTgt',
        'vEgo', 'std', 'acc05st', 'cruiseEn', 'cruiseV', 'LS_res', 'LS_set', 'LS_spd+',
        'primAnz', 'zl', 'bus128seen')

rows = []
for f in FILES:
  route = f.split('_trace_')[1][:8]
  with open(f) as fh:
    next(fh)
    for ln in fh:
      p = ln.rstrip('\n').split('\t')
      if len(p) < 21:
        continue
      try:
        # vis_dRel 列记录的是 modelV2.leadsV3[0].x[0]（摄像头参考系）；雷达侧 dRel 是
        # "车头前"参考系 → 统一减 RADAR_TO_CAMERA=1.52（与 B1 拟合口径一致）。
        rows.append((route, p[0], float(p[1]), int(float(p[2])), float(p[4]) - 1.52,
                     int(float(p[5])), float(p[6]), float(p[10])))
      except ValueError:
        continue
print(f'trace 文件 {len(FILES)} 个，总帧 {len(rows)}')

# 采样 dt（用于冻结时长判定）：按 (route,seg) 的 时间跨度/帧数 估算
groups = {}
for k, (route, seg, T, *_ ) in enumerate(rows):
  groups.setdefault((route, seg), []).append(T)
dts = []
for k, ts in groups.items():
  if len(ts) > 10 and ts[-1] > ts[0]:
    dts.append((ts[-1] - ts[0]) / (len(ts) - 1))
dt_med = float(np.median(dts)) if dts else 0.01
print(f'估算采样周期 dt 中位 = {dt_med:.4f}s（冻结判据用 {max(1, int(round(0.5 / dt_med)))} 帧 ≈ 0.5 s）')

N_FRZ = max(1, int(round(0.5 / dt_med)))
frozen = np.zeros(len(rows), dtype=bool)
i = 0
while i < len(rows):
  j = i + 1
  while j < len(rows) and rows[j][0] == rows[i][0] and rows[j][1] == rows[i][1] and rows[j][3] == rows[i][3]:
    j += 1
  if (j - i) >= N_FRZ and 1 <= rows[i][3] <= 1020:
    if max(rows[k][7] for k in range(i, j)) < 2.0:
      frozen[i:j] = True
  i = j

# ---- 逐帧量 ----
rec = []
for k, (route, seg, T, idx, vis, radar, fused, v) in enumerate(rows):
  if not (1 <= idx <= 1020) or vis <= 0.5:
    continue
  d_rad = (A * idx + B) * max(v, FLOOR_V)
  rec.append(dict(route=route, seg=seg, T=T, idx=idx, vis=vis, fused=fused, v=v,
                  d_rad=d_rad, delta=d_rad - vis, frz=bool(frozen[k])))
print(f'可用帧（idx 有效 ∧ 视觉有效）: {len(rec)}')

bands = [(0.0, 2.0), (2.0, 4.0), (4.0, 8.0), (8.0, 15.0), (15.0, 200.0)]
print('\n=== A. 各速度带：d_rad(B1) vs d_vis，及"照搬丰田门"的接受率 ===')
print(f"{'v带(m/s)':<11}{'n':>7}{'Δ中位':>8}{'|Δ|中位':>9}{'Δ>0占比':>9}{'丰田门拒绝率':>12}{'冻结帧n':>8}{'冻结帧丰田门接受率':>18}")
for lo, hi in bands:
  m = np.array([lo <= r['v'] < hi for r in rec])
  n = int(m.sum())
  if n == 0:
    continue
  d = np.array([r['delta'] for r in rec])[m]
  vis = np.array([r['vis'] for r in rec])[m]
  tol = np.maximum(TOY_REL * vis, TOY_ABS)
  rej = float(np.mean(np.abs(d) > tol))
  frz = np.array([r['frz'] for r in rec])[m]
  nf = int(frz.sum())
  acc_frz = float(np.mean(np.abs(d[frz]) <= tol[frz])) if nf else float('nan')
  print(f'{lo:>4}-{hi:<6}{n:>7}{np.median(d):>8.2f}{np.median(np.abs(d)):>9.2f}'
        f'{100*np.mean(d>0):>8.1f}%{100*rej:>11.1f}%{nf:>8}'
        f'{(100*acc_frz if nf else float("nan")):>17.1f}%')

print('\n=== B. 低速/静止（v<2）长冻结窗口：现实现 vs 视觉为准 vs 丰田门 ===')
print(f"{'route/seg':<18}{'idx':>5}{'秒':>7}{'v':>6}{'d_vis':>8}{'d_rad':>8}{'融后dRel':>9}{'|Δrad-vis|':>11}{'丰田门':>7}")
seen = {}
for r in rec:
  if not r['frz'] or r['v'] >= 2.0:
    continue
  key = (r['route'], r['seg'], r['idx'])
  if key in seen:
    continue
  seen[key] = 1
  tol = max(TOY_REL * r['vis'], TOY_ABS)
  gate = '接受' if abs(r['delta']) <= tol else '拒绝'
  print(f"{r['route']+'/'+r['seg']:<18}{r['idx']:>5}{r['T']:>7.1f}{r['v']:>6.2f}"
        f"{r['vis']:>8.2f}{r['d_rad']:>8.2f}{r['fused']:>9.2f}{abs(r['delta']):>11.2f}{gate:>7}")

print('\n=== C. 三段口径相对"视觉为准"的偏离（低/静止 v<2 帧）===')
m = np.array([r['v'] < 2.0 for r in rec])
if m.sum():
  vis = np.array([r['vis'] for r in rec])[m]
  fused = np.array([r['fused'] for r in rec])[m]
  d_rad = np.array([r['d_rad'] for r in rec])[m]
  d_min = np.minimum(vis, d_rad)     # 视觉为准 + 雷达只在更近时接管（丰田低速精神）
  print(f'{"口径":<28}{"中位|Δ vs 视觉|":>16}{"P90":>8}{"判远(>视觉+1m)占比":>20}')
  for name, x in (('现实现 A2 融合 dRel', fused), ('纯 B1 雷达 t*max(v,5)', d_rad),
                  ('min(视觉, 雷达) 低速兜底', d_min)):
    e = x - vis
    print(f'{name:<28}{np.median(np.abs(e)):>16.2f}{np.percentile(np.abs(e), 90):>8.2f}'
          f'{100 * np.mean(e > 1.0):>19.1f}%')
