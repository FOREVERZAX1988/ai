#!/usr/bin/env python3
"""Q3 复核 v2：以 modelV2 原始视觉为真值（radar 参考系 = vis_dRel - 1.52），
比较 现状 t*max(v,5) / 候选公式B / idx/30。
列: seg T idx2 idx128 vis_dRel radar dRel vRel vLead aTgt vEgo std acc05st cruiseEn cruiseV LS_res LS_set LS_spd+ primAnz zl bus128seen
"""
import glob
import numpy as np
from collections import defaultdict

A, B = 0.008969, 0.332
DEF_FLOOR = 5.0


def t_idx(i):
  return A * i + B


def d_cur(i, v):
  return t_idx(i) * max(v, DEF_FLOOR)


def d_candB(i, v):
  return 2.3465 * t_idx(i) * np.sqrt(max(v, 1.0)) + 1.08


rows = []
for f in sorted(glob.glob('/data/openpilot/ai/tools/_trace_00000*.txt')):
  name = f.split('_trace_')[1][:8]
  with open(f) as fh:
    fh.readline()
    for ln in fh:
      p = ln.rstrip('\n').split('\t')
      if len(p) < 21:
        continue
      try:
        rows.append((name, float(p[1]), float(p[2]), float(p[4]), int(p[5]), float(p[6]),
                     float(p[7]), float(p[10])))
      except ValueError:
        continue
print(f'总行 {len(rows)}')
name = np.array([r[0] for r in rows])
T = np.array([r[1] for r in rows]); idx = np.array([r[2] for r in rows])
vis = np.array([r[3] for r in rows]); radflag = np.array([r[4] for r in rows])
dRel = np.array([r[5] for r in rows]); vRel = np.array([r[6] for r in rows]); v = np.array([r[7] for r in rows])
truth = vis - 1.52            # 雷达参考系的视觉真值

# --- A. 融合是否覆盖了视觉（诊断，非评价） ---
m = (vis > 1.0) & (2 <= idx) & (idx < 1021)
print(f"\n[A] 有有效 idx 的帧 n={int(m.sum())}；其中 |(vis-1.52) - dRel| > 1m 的比例 = "
      f"{100*np.mean(np.abs(truth[m]-dRel[m]) > 1.0):.1f}%  (>3m: {100*np.mean(np.abs(truth[m]-dRel[m]) > 3.0):.1f}%)")

# --- B. 静止域：idx 冻结样本 vs 视觉真值 ---
m2 = (v < 0.15) & (2 <= idx) & (idx < 1021) & (vis > 1.0)
g = defaultdict(list)
for i in np.where(m2)[0]:
  g[(name[i], int(idx[i]))].append(truth[i])
print('\n[B] 静止样本(v<0.15, 出现>=5 帧的唯一 route+idx)：真值 = vis_x0 - 1.52')
print(f"{'route':<9}{'idx':>5}{'n':>6}{'vis_x0':>8}{'真值':>7}{'现状':>7}{'Δ':>7}{'idx/30':>8}{'Δ':>7}{'candB':>7}{'Δ':>7}")
agg_cur, agg_b30, agg_cb = [], [], []
for k, vs in sorted(g.items()):
  if len(vs) < 5:
    continue
  tv = float(np.median(vs)); i0 = k[1]
  d1 = d_cur(i0, 0.0); d2 = i0 / 30.0; d3 = d_candB(i0, 0.0)
  agg_cur.append(d1 - tv); agg_b30.append(d2 - tv); agg_cb.append(d3 - tv)
  print(f'{k[0]:<9}{i0:>5}{len(vs):>6}{tv+1.52:>8.2f}{tv:>7.2f}{d1:>7.2f}{d1-tv:>+7.2f}'
        f'{d2:>8.2f}{d2-tv:>+7.2f}{d3:>7.2f}{d3-tv:>+7.2f}')
for nm, a in (('现状 t*5', agg_cur), ('idx/30', agg_b30), ('候选B', agg_cb)):
  print(f'  → 静止样本 {nm:<9} n={len(a):>3} med|Δ|={np.median(np.abs(a)):5.2f}m  中位偏差={np.median(a):+5.2f}m')

# --- C. 移动域：以 vis-1.52 为真值 ---
m3 = (vis > 1.5) & (2 <= idx) & (idx < 1021) & (abs(vRel) <= 0.3) & (v > 0.5)
print(f'\n[C] 移动域 n={int(m3.sum())}（真值=vis_x0-1.52, |vRel|<=0.3）')
print(f"{'v带(m/s)':<12}{'n':>7}{'现状med|Δ|':>12}{'现状判远%':>11}{'现状判近%':>11}"
      f"{'candB med|Δ|':>14}{'candB判远%':>12}{'candB判近%':>12}{'idx/30 med|Δ|':>15}")
for lo, hi in ((0.5, 2), (2, 3), (3, 5), (5, 8), (8, 15), (15, 30)):
  s = m3 & (v >= lo) & (v < hi)
  if s.sum() < 50:
    continue
  dc = np.array([d_cur(i, vv) for i, vv in zip(idx[s], v[s])]) - truth[s]
  db = np.array([d_candB(i, vv) for i, vv in zip(idx[s], v[s])]) - truth[s]
  d30 = idx[s] / 30.0 - truth[s]
  print(f'{lo:>5}-{hi:<6}{int(s.sum()):>7}{np.median(abs(dc)):>12.2f}{100*np.mean(dc>2):>11.1f}'
        f'{100*np.mean(dc<-2):>11.1f}{np.median(abs(db)):>14.2f}{100*np.mean(db>2):>12.1f}'
        f'{100*np.mean(db<-2):>12.1f}{np.median(abs(d30)):>15.2f}')

# --- D. route 91 事故段复现 ---
s = (name == '00000091') & (T >= 671) & (T <= 678)
print('\n[D] route 91 停稳段: 真值/现状/candB')
print(f"{'T':>7}{'idx':>5}{'v':>6}{'真值':>7}{'现状':>7}{'candB':>7}{'dRel':>7}{'idx/30':>7}")
last = -9
for i in sorted(np.where(s)[0], key=lambda i: T[i]):
  if T[i] - last < 1.0:
    continue
  last = T[i]
  print(f'{T[i]:>7.1f}{int(idx[i]):>5}{v[i]:>6.2f}{truth[i]:>7.2f}{d_cur(idx[i], v[i]):>7.2f}'
        f'{d_candB(idx[i], v[i]):>7.2f}{dRel[i]:>7.2f}{idx[i]/30:>7.2f}')
