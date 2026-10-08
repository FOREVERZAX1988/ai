#!/usr/bin/env python3
"""Q3 复核：候选公式B(√v) vs min-规则 vs 现状；静止冻结 idx 样本对照。
数据：ai/tools/_trace_*.txt  (列: seg T idx2 idx128 vis_dRel radar dRel vRel vLead aTgt vEgo std acc05st cruiseEn cruiseV LS_res LS_set LS_spd+ primAnz zl bus128seen)
"""
import glob
import numpy as np

A, B = 0.008969, 0.332
VC = 3.0


def t_idx(i):
  return A * i + B


def f_cur(i, v):
  return t_idx(i) * max(v, 5.0)


def f_candB(i, v):
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
                     float(p[7]), float(p[10]), float(p[19])))
      except ValueError:
        continue
print(f'总行 {len(rows)}')
R = {n: np.array([r[1:] for r in rows if r[0] == n]) for n in sorted({r[0] for r in rows})}
for n, a in R.items():
  print(f'  route {n}: {len(a)} 行  T {a[:,0].min():.0f}..{a[:,0].max():.0f}')

# --- 0. 参考系偏移：radar==0(纯视觉 lead) 时 dRel 与 vis_dRel 的关系 ---
m0 = np.array([(r[3], r[5]) for r in rows if r[4] == 0 and r[3] > 1 and r[5] > 1])
print(f'\n[0] radar==0 有 lead 帧 n={len(m0)}  vis_dRel-dRel: 中位={np.median(m0[:,0]-m0[:,1]):+.2f} 均值={np.mean(m0[:,0]-m0[:,1]):+.2f}')
m1 = np.array([(r[3], r[5]) for r in rows if r[4] == 1 and r[3] > 1 and r[5] > 1])
print(f'    radar==1 有 lead 帧 n={len(m1)}  vis_dRel-dRel: 中位={np.median(m1[:,0]-m1[:,1]):+.2f} 均值={np.mean(m1[:,0]-m1[:,1]):+.2f}')

# --- 1. 静止/极低速(idx 冻结)样本：唯一 (route, idx) ---
print('\n[1] 静止样本 v<0.15，唯一(route,idx) —— 真值用 vis_dRel 与其 -1.52 两口径')
print(f"{'route':<9}{'idx':>5}{'v':>6}{'vis_x0':>8}{'vis-1.52':>9}{'现状t*5':>9}{'idx/30':>8}{'candB':>8}")
seen = set()
for r in sorted(rows, key=lambda r: (r[0], r[2])):
  name, T, idx, vis, radar, dRel, vRel, v, zl = r
  if v < 0.15 and 2 <= idx < 1021 and (name, int(idx)) not in seen:
    seen.add((name, int(idx)))
    print(f'{name:<9}{int(idx):>5}{v:>6.2f}{vis:>8.2f}{vis-1.52:>9.2f}{f_cur(idx,v):>9.2f}{idx/30:>8.2f}{f_candB(idx,v):>8.2f}')

# --- 2. 移动域精度：三种方案对“视觉真值”的偏差 ---
print('\n[2] 偏差 Δ = 方案值 − 视觉真值 (radar==0 帧，|vRel|<=0.3, idx∈[2,1021))')
print('    真值=该帧 dRel(=视觉口径)。注: 该子集里 min-规则恒 <= 真值 → 天然不判远(自证偏置)')
sub = [(r[2], r[7], r[5]) for r in rows if r[4] == 0 and r[5] > 0.5 and 2 <= r[2] < 1021
       and abs(r[6]) <= 0.3 and r[7] > 0.5]
idx = np.array([s[0] for s in sub]); v = np.array([s[1] for s in sub]); truth = np.array([s[2] for s in sub])
cur = np.array([f_cur(i, vv) for i, vv in zip(idx, v)])
cb = np.array([f_candB(i, vv) for i, vv in zip(idx, v)])
for lo, hi in ((0.5, 3), (3, 5), (5, 8), (8, 15), (15, 30)):
  mm = (v >= lo) & (v < hi)
  if mm.sum() < 50:
    continue
  d_cur = cur[mm] - truth[mm]
  d_cb = cb[mm] - truth[mm]
  print(f'  v∈[{lo},{hi}) n={int(mm.sum()):>6}  现状 med|Δ|={np.median(abs(d_cur)):5.2f}m 判远>2m={100*np.mean(d_cur>2):5.1f}%  '
        f'| candB med|Δ|={np.median(abs(d_cb)):5.2f}m 判远>2m={100*np.mean(d_cb>2):5.1f}%')

# --- 3. route 91 seg9 事故段逐帧 ---
print('\n[3] route 91 事故段：T∈[668,690] 每 0.5s 采样')
a = R['00000091']
last = -9
for r in a:
  T, idx, vis, radar, dRel, vRel, v, zl = r
  if 668 <= T <= 690 and T - last >= 0.5:
    last = T
    mn = min(vis - 1.52, f_cur(idx, v)) if v < VC else f_cur(idx, v)
    print(f'  T={T:7.1f} v={v:5.2f} idx={int(idx):4d} vis={vis:5.2f} dRel={dRel:5.2f} '
          f'现状={f_cur(idx,v):5.2f} min(vis-1.52,现状)={mn:5.2f} candB={f_candB(idx,v):5.2f} radar={radar}')
