#!/usr/bin/env python3
"""同一 route 内 zl 效应检验（去速度混淆：t=d_vis/v，同 idx 桶比较）。
用法: zl_matched_idx_0910.py route1 route2 ..."""
import sys, numpy as np
SC="/data/openpilot/ai/tools/.scan2"
for rt in sys.argv[1:]:
    d=np.load(f"{SC}/{rt}.npz")
    idx,zl,v,dv = d['idx'],d['zl'],d['v'],d['dv']
    t=dv/np.maximum(v,5.0)
    print(f"\n=== {rt}  n={len(idx)}   v中位={np.median(v)*3.6:.1f}km/h ===")
    print(f"{'idx桶':>10} {'n3/n4':>10} {'v3/v4(km/h)':>13} {'t_vis3':>7} {'t_vis4':>7} {'Δ(zl3-zl4)':>10} {'相对':>7}")
    for lo in range(100,600,50):
        m=(idx>=lo)&(idx<lo+50)
        m3,m4=m&(zl==3),m&(zl==4)
        if m3.sum()<150 or m4.sum()<150: continue
        t3,t4=np.median(t[m3]),np.median(t[m4])
        v3,v4=np.median(v[m3])*3.6,np.median(v[m4])*3.6
        print(f"{lo:>4}-{lo+50:<5} {m3.sum():>5}/{m4.sum():<5} {v3:>6.1f}/{v4:<6.1f} {t3:>7.3f} {t4:>7.3f} {t3-t4:>+10.3f} {100*(t3-t4)/max(t4,.1):>6.1f}%")
    # 全段
    a,b=(zl==3),(zl==4)
    if a.sum()>500 and b.sum()>500:
        print(f"全段: t3={np.median(t[a]):.3f} t4={np.median(t[b]):.3f} Δ={np.median(t[a])-np.median(t[b]):+.3f}")
