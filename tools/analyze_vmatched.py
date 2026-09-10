#!/usr/bin/env python3
"""同 idx 分箱 + 同速度分箱 下的 t_vis(视觉时距) 对照：跨 route/ZL 直接可比。
输出每行 (idxbin, vbin) 下各 (route,ZL) 组的中位 t_vis 与样本数。"""
import glob, os, collections
import numpy as np
IDXB = [(100,150),(150,200),(200,250),(250,300),(300,350),(350,400),(400,450),(450,500),(500,560)]
VB = [(6,8),(8,10),(10,12),(12,14),(14,16)]
groups = {}
for f in sorted(glob.glob('/data/openpilot/ai/tools/.scan2/*.npz')):
    rt = os.path.basename(f)[:-4][-4:]
    d = np.load(f)
    idx, zl, v, dv = d['idx'], d['zl'], d['v'], d['dv']
    tv = dv / np.maximum(v, 5.0)
    for z in sorted(set(zl.astype(int))):
        groups[(rt, z)] = (idx, v, tv, zl)
print("每组: t_vis 中位 (n)   —— 同 idx 同速度下，视觉时距是否一致")
for lo, hi in IDXB:
    for vlo, vhi in VB:
        cells = []
        for (rt, z), (idx, v, tv, zl) in sorted(groups.items()):
            m = (zl == z) & (idx >= lo) & (idx < hi) & (v >= vlo) & (v < vhi)
            if m.sum() >= 150:
                cells.append((f"{rt}/Z{z} {np.median(tv[m]):.2f}s({m.sum()})", np.median(tv[m])))
        if len(cells) >= 2:
            vals = [c[1] for c in cells]
            spread = max(vals) - min(vals)
            print(f"idx {lo:>3}-{hi:<3} v {vlo:>2}-{vhi:<2}m/s  跨度{spread:.2f}s | " + " | ".join(c[0] for c in cells))
