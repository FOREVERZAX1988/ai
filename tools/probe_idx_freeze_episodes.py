#!/usr/bin/env python3
"""1) idx 冻结 episode 统计：冻结时长 / 冻结期间 vEgo 上限 / 解冻时的 vEgo（数据驱动的"失效域"边界）
   2) 低速域 idx->车距 标定是否可行：冻结帧是否污染拟合
用法: probe_idx_freeze_episodes.py 00000091,0000007a,0000007b [vfit_max]
"""
import glob, sys
import numpy as np
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader
BASE = '/data/media/0/realdata'
A, B, CAMS = 0.008969, 0.332, 1.52
MIN_DUR = 0.5
VFIT = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0

eps = []      # (dur, maxv, v_at_release, idx, vlead_max)
fit_all, fit_fresh = [], []

for pref in sys.argv[1].split(','):
    for f in sorted(glob.glob(f'{BASE}/{pref}--*/rlog.zst'),
                    key=lambda p: int(p.split('--')[-1].split('/')[0])):
        cur_idx = 0.0; vlead = None; x0 = None; prob = None
        seq = []
        for m in LogReader(f):
            w = m.which()
            if w == 'can':
                for c in m.can:
                    if c.src != 2 or len(c.dat) < 7: continue
                    if c.address == 780:
                        cur_idx = float((c.dat[3] | (c.dat[4] << 8)) & 0x3FF)
                    elif c.address == 0x324:
                        vl = (c.dat[5] | ((c.dat[6] & 0x03) << 8)) * 0.32
                        vlead = None if vl >= 320 else vl/3.6
            elif w == 'carState':
                seq.append([m.logMonoTime/1e9, float(m.carState.vEgo), cur_idx, vlead, x0, prob])
            elif w == 'modelV2':
                try:
                    ld = m.modelV2.leadsV3
                    if len(ld) > 0 and len(ld[0].x) > 0:
                        x0 = float(ld[0].x[0]); prob = float(ld[0].prob)
                except Exception: pass
        # --- 1) episodes
        i = 0
        while i < len(seq):
            if not (1 <= seq[i][2] <= 1020):
                i += 1; continue
            j = i
            while j+1 < len(seq) and seq[j+1][2] == seq[i][2]:
                j += 1
            dur = seq[j][0] - seq[i][0]
            if dur >= MIN_DUR:
                maxv = max(seq[k][1] for k in range(i, j+1))
                vrel = seq[j+1][1] if j+1 < len(seq) else None
                vlmax = max((seq[k][3] for k in range(i, j+1) if seq[k][3] is not None), default=None)
                eps.append((dur, maxv, vrel, seq[i][2], vlmax, f'{pref[-2:]}.{f.split(chr(45)*2)[-1].split(chr(47))[0]}'))
            i = j+1
        # --- 2) 拟合样本（视觉前车有效 ∧ idx 有效）
        last_chg_t = -999.0; last_val = None
        for t, v, ix, vl, x, p in seq:
            if not (1 <= ix <= 1020): continue
            if ix != last_val:
                last_val = ix; last_chg_t = t
            if not (x is not None and p is not None and p > 0.5): continue
            d = x - CAMS
            if not (0.5 < d < 50.0 and v < VFIT): continue
            fresh = (t - last_chg_t) < 0.5
            fit_all.append((ix, v, d))
            if fresh: fit_fresh.append((ix, v, d))

pass
print(f'=== 冻结 episode（同一有效 idx 保持 >= {MIN_DUR}s）: n={len(eps)} ===')
if len(eps):
    tags = [e[5] for e in eps]
    eps = np.array([e[:5] for e in eps], float) if eps else np.zeros((0,5))
    dur, maxv, vrel, idxv, vlmax = eps[:,0], eps[:,1], eps[:,2], eps[:,3], eps[:,4]
    ok = ~np.isnan(vrel)
    print(f'  时长: P50={np.percentile(dur,50):.1f}s P90={np.percentile(dur,90):.1f}s MAX={dur.max():.1f}s  总时长={dur.sum():.0f}s')
    print(f'  冻结期间 vEgo 上限: P50={np.percentile(maxv,50):.2f} P90={np.percentile(maxv,90):.2f} P99={np.percentile(maxv,99):.2f} MAX={maxv.max():.2f} m/s')
    print(f'  解冻瞬间 vEgo    : P50={np.percentile(vrel[ok],50):.2f} P90={np.percentile(vrel[ok],90):.2f} m/s')
    for thr in (1.0, 1.5, 2.0, 2.5, 3.0):
        print(f'    vEgo_max < {thr}: {int((maxv<thr).sum())}/{len(eps)} episodes ({100*np.mean(maxv<thr):.0f}%)  覆盖时长占比 {100*dur[maxv<thr].sum()/dur.sum():.0f}%')
    print(f'  长冻结(>3s) 的 idx 值分布: ' + ', '.join(f'{v}' for v in np.unique(eps[dur>3][:,0].astype(int))[:20]) if False else '')
    for thr in (1.0, 1.5, 2.0, 2.5, 3.0, 5.0):
        big = dur >= 1.5
        if big.sum():
            print(f'  仅看>=1.5s 的冻结: n={int(big.sum())} 总时长={dur[big].sum():.0f}s | maxVego P90={np.percentile(maxv[big],90):.2f} MAX={maxv[big].max():.2f} | maxVego<{thr}: {int((maxv[big]<thr).sum())}/{int(big.sum())} 时长占比 {100*dur[big][maxv[big]<thr].sum()/dur[big].sum():.0f}%')
    print('  长冻结(>=3s) 明细 [时长s, maxVego, 解冻时v, idx, 冻结期vLead_max]:')
    for k in np.where(dur >= 3)[0]:
        e = eps[k]
        print(f'    {tags[k]:8s} {e[0]:6.1f}s  maxV={e[1]:5.2f}  v_rel(解冻时)={e[2]:5.2f}  idx={int(e[3]):4d}  vLead_max={"n/a" if np.isnan(e[4]) else format(e[4],".2f")}')

def fitrep(tag, arr):
    arr = np.array(arr)
    if len(arr) < 50:
        print(f'  {tag}: n={len(arr)} 样本不足'); return
    I, V, D = arr[:,0], arr[:,1], arr[:,2]
    a, b = np.polyfit(I, D, 1)
    e = a*I + b - D
    t = B + A*I
    e2 = t*np.maximum(V, 5.0) - D
    e3 = t*np.maximum(V, 2.0) - D
    e4 = I/30.0 - D
    print(f'  {tag}: n={len(arr):6d} v={V.min():.2f}..{V.max():.2f} | 线性拟合 d={a:.5f}*idx{b:+.3f} RMS={np.sqrt(np.mean(e**2)):5.2f}m '
          f'| 现行 t*max(v,5) MAE={np.median(np.abs(e2)):5.2f}m | t*max(v,2) MAE={np.median(np.abs(e3)):5.2f}m | idx/30 MAE={np.median(np.abs(e4)):5.2f}m')

print(f'\n=== 低速域(v<{VFIT} m/s) idx->车距 标定可行性 ===')
fitrep('全部样本(含冻结帧)', fit_all)
fitrep('只保留 idx 新鲜(<0.5s 内有变化)', fit_fresh)
