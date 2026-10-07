#!/usr/bin/env python3
"""量化"视觉主导 + 雷达只能改近"方案对 冻结idx 的拦截效果：
 在长冻结(>=1.5s)期间，比较 冻结idx 换算距离 d_stale = t(idx)*max(v,5) 与 视觉距离 d_vis = cam_x0-1.52
 统计: d_stale 比视觉更近(会被"只能改近"规则采纳 => 危险) 的比例 / 更远(被拦) 的比例
并给出若错误采纳时的距离误差。
用法: probe_stale_radar_risk.py 00000091,0000007a,0000007b
"""
import glob, sys
import numpy as np
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader
BASE = '/data/media/0/realdata'
A, B, CAMS = 0.008969, 0.332, 1.52

rows = []
for pref in sys.argv[1].split(','):
    for f in sorted(glob.glob(f'{BASE}/{pref}--*/rlog.zst'),
                    key=lambda p: int(p.split('--')[-1].split('/')[0])):
        seg = f.split('--')[-1].split('/')[0]
        cur_idx = 0.0; x0 = None; prob = None
        seq = []
        for m in LogReader(f):
            w = m.which()
            if w == 'can':
                for c in m.can:
                    if c.src == 2 and c.address == 780 and len(c.dat) >= 7:
                        cur_idx = float((c.dat[3] | (c.dat[4] << 8)) & 0x3FF)
            elif w == 'carState':
                seq.append([m.logMonoTime/1e9, float(m.carState.vEgo), cur_idx, x0, prob])
            elif w == 'modelV2':
                try:
                    ld = m.modelV2.leadsV3
                    if len(ld) > 0 and len(ld[0].x) > 0:
                        x0 = float(ld[0].x[0]); prob = float(ld[0].prob)
                except Exception: pass
        # 找出 >=1.5s 的冻结区间
        i = 0
        while i < len(seq):
            if not (1 <= seq[i][2] <= 1020): i += 1; continue
            j = i
            while j+1 < len(seq) and seq[j+1][2] == seq[i][2]: j += 1
            if seq[j][0] - seq[i][0] >= 1.5:
                for k in range(i, j+1):
                    t, v, ix, x, p = seq[k]
                    if x is None or p is None or p <= 0.5: continue
                    dv = x - CAMS
                    if not (0.5 < dv < 60): continue
                    ds = (A*ix + B) * max(v, 5.0)
                    rows.append((pref, seg, dv, ds, v, ix))
            i = j+1

rows = np.array([(r[2], r[3], r[4], r[5]) for r in rows], float)
print(f'长冻结(>=1.5s)期间 且视觉有前车 的样本: n={len(rows)}')
if len(rows):
    dv, ds, v, ix = rows[:,0], rows[:,1], rows[:,2], rows[:,3]
    closer = ds < dv - 1.0     # 冻结值比视觉"更近" => "只能改近"规则会采纳 => 危险
    far    = ds > dv + 1.0
    same   = ~(closer | far)
    print(f'  d_stale 比视觉更远(被"只能改近"拦掉): {100*np.mean(far):5.1f}%')
    print(f'  d_stale 与视觉接近(|Δ|<=1m)          : {100*np.mean(same):5.1f}%')
    print(f'  d_stale 比视觉更近(会误采纳)          : {100*np.mean(closer):5.1f}%')
    print(f'  d_stale 中位={np.median(ds):5.2f}m  视觉中位={np.median(dv):5.2f}m  '
          f'两者差中位={np.median(ds-dv):+5.2f}m')
    if closer.sum():
        print(f'  会误采纳样本里: d_stale 中位={np.median(ds[closer]):.2f}m 视觉中位={np.median(dv[closer]):.2f}m '
              f'虚近量中位={np.median(dv[closer]-ds[closer]):.2f}m (最大 {np.max(dv[closer]-ds[closer]):.2f}m)')
        print(f'    这些样本的 vEgo 中位={np.median(v[closer]):.2f} m/s, idx 值分布: '
              + ', '.join(str(int(x)) for x in np.unique(ix[closer])[:15]))
    print(f'  冻结期间 vEgo: P50={np.percentile(v,50):.2f} MAX={v.max():.2f} m/s')
    # 若用 t(idx)*max(v,2) 换算
    ds2 = (A*ix + B) * np.maximum(v, 2.0)
    print(f'  换成 t(idx)*max(v,2) 后: 更远 {100*np.mean(ds2<dv-1):5.1f}% / 接近 {100*np.mean(np.abs(ds2-dv)<=1):5.1f}% / '
          f'更近 {100*np.mean(ds2>dv+1):5.1f}%')
    ds3 = ix/30.0
    print(f'  换成 d=idx/30       后: 更远 {100*np.mean(ds3<dv-1):5.1f}% / 接近 {100*np.mean(np.abs(ds3-dv)<=1):5.1f}% / '
          f'更近 {100*np.mean(ds3>dv+1):5.1f}%')
