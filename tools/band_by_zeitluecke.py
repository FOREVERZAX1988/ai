#!/usr/bin/env python3
"""按 原厂跟车档位 Zeitluecke(3/4) 拆分，对比 旧153表/新线性公式 vs 视觉。
若档位3与档位4的 vis-old 明显不同 -> 证实 idx 标度依赖档位。"""
import json, glob, os
import numpy as np
IDX_TAB=np.array(json.load(open('/data/openpilot/ai/tools/abstands_idx_table.json')))
T_TAB=np.array(json.load(open('/data/openpilot/ai/tools/abstands_t_table.json')))
def t_old(idx): return np.interp(idx,IDX_TAB,T_TAB)
def t_new(idx):
    idx=np.asarray(idx,dtype=float); t=0.008718*idx+1.0178
    return np.where(idx<100,0.8,np.where(idx>560,6.0,t))
D={}
for f in sorted(glob.glob('/data/openpilot/ai/tools/.scan/*.npz')):
    z=np.load(f); rt=os.path.basename(f)[:-4]
    if 'zl' not in z: print(f'[skip no zl] {rt}'); continue
    D[rt]=(z['idx'],z['v'],z['dvis'],z['zl'])
    print(f'[load] {rt} n={len(z["idx"])} zl分布={dict(zip(*np.unique(z["zl"],return_counts=True)))}')

bands=[(0,15),(15,25),(25,40),(40,60),(60,90),(90,130),(130,1000)]
for setting in (3,4):
    print(f"\n######## 档位 Zeitluecke={setting} ########")
    idx=[];v=[];dv=[]
    for rt,(i,vv,d,z) in D.items():
        m=(z==setting); idx.append(i[m]);v.append(vv[m]);dv.append(d[m])
    idx=np.concatenate(idx);v=np.concatenate(v);dv=np.concatenate(dv)
    if len(idx)<200: print("  样本不足"); continue
    dold=t_old(idx)*np.maximum(v,5);dnew=t_new(idx)*np.maximum(v,5)
    print(f"  N={len(idx)}  idx中位={np.median(idx):.0f}  v中位={np.median(v)*3.6:.0f}km/h  vis-old全段={np.median(dv-dold):+.2f}  vis-new={np.median(dv-dnew):+.2f}")
    print(f"  {'band':>9} {'n':>7} {'d_vis':>6} {'d_old':>6} {'d_new':>6} {'vis-old':>8} {'vis-new':>8}")
    for lo,hi in bands:
        m=(dv>=lo)&(dv<hi)
        if m.sum()<50: continue
        print(f"  {lo:>4}-{hi:<5} {int(m.sum()):>7} {np.median(dv[m]):>6.1f} {np.median(dold[m]):>6.1f} {np.median(dnew[m]):>6.1f} {np.median(dv[m]-dold[m]):>+8.1f} {np.median(dv[m]-dnew[m]):>+8.1f}")
