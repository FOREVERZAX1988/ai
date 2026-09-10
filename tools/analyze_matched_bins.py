#!/usr/bin/env python3
"""同一 idx 分箱内比较：不同 ZL/route 的 t_vis(视觉时距) vs t_old / t_new。"""
import glob, json, os
import numpy as np
IDX_TAB = np.array(json.load(open('/data/openpilot/ai/tools/abstands_idx_table.json')))
T_TAB = np.array(json.load(open('/data/openpilot/ai/tools/abstands_t_table.json')))
BINS = [100, 150, 200, 250, 300, 350, 400, 450, 500, 560]
t_old = lambda i: np.interp(i, IDX_TAB, T_TAB)
t_new = lambda i: np.clip(np.where(i < 100, 0.8, 0.008718 * i + 1.0178), None, 6.0)
hdr = f"{'route':>6} {'ZL':>2} {'idxbin':>8} {'n':>6} {'v':>5} {'t_vis':>6} {'t_old':>6} {'t_new':>6} {'dt_old':>7} {'dt_new':>7} {'g_old':>6} {'g_new':>6}"
print(hdr)
for f in sorted(glob.glob('/data/openpilot/ai/tools/.scan2/*.npz')):
    rt = os.path.basename(f)[:-4][-4:]
    d = np.load(f)
    idx, zl, v, dv, gate = d['idx'], d['zl'], d['v'], d['dv'], d['gate']
    tv = dv / np.maximum(v, 5.0)
    do, dn = tv - t_old(idx), tv - t_new(idx)
    for z in sorted(set(zl.astype(int))):
        for lo, hi in zip(BINS[:-1], BINS[1:]):
            m = (zl == z) & (idx >= lo) & (idx < hi)
            if m.sum() < 150: continue
            g = m & gate
            gs = lambda a: (f"{np.median(a[g]):+.2f}" if g.sum() > 50 else "  -  ")
            print(f"{rt:>6} {z:>2} {f'{lo}-{hi}':>8} {int(m.sum()):>6} {np.median(v[m])*3.6:>5.0f} "
                  f"{np.median(tv[m]):>6.2f} {t_old(np.median(idx[m])):>6.2f} {t_new(np.median(idx[m])):>6.2f} "
                  f"{np.median(do[m]):>+7.2f} {np.median(dn[m]):>+7.2f} {gs(do):>6} {gs(dn):>6}")
