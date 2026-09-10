#!/usr/bin/env python3
"""读取各 route 落盘的 npz(idx,v,dvis)，池化后按视觉距离分桶，
看 旧153表 vs 新线性公式 vs 视觉 在各距离段的偏差。"""
import json, glob, os
import numpy as np
IDX_TAB=np.array(json.load(open('/data/openpilot/ai/tools/abstands_idx_table.json')))
T_TAB=np.array(json.load(open('/data/openpilot/ai/tools/abstands_t_table.json')))
def t_old(idx): return np.interp(idx,IDX_TAB,T_TAB)
def t_new(idx):
    idx=np.asarray(idx,dtype=float)
    t=0.008718*idx+1.0178
    t=np.where(idx<100,0.8,t); t=np.where(idx>560,6.0,t)
    return t

idx=[];v=[];dv=[]
for f in sorted(glob.glob('/data/openpilot/ai/tools/.scan/*.npz')):
    z=np.load(f); idx.append(z['idx']);v.append(z['v']);dv.append(z['dvis'])
    print(f'[load] {os.path.basename(f)} n={len(z["idx"])}')
idx=np.concatenate(idx);v=np.concatenate(v);dv=np.concatenate(dv)
dold=t_old(idx)*np.maximum(v,5.0); dnew=t_new(idx)*np.maximum(v,5.0)
print(f'\n总 N={len(idx)}')
bands=[(0,15),(15,25),(25,40),(40,60),(60,90),(90,130),(130,1000)]
print(f"\n{'band(m)':>9} {'n':>8} {'d_vis':>6} {'d_old':>6} {'d_new':>6} {'vis-old':>7} {'vis-new':>8} {'≤5m o/n%':>8} {'新/旧':>6}")
for lo,hi in bands:
    m=(dv>=lo)&(dv<hi)
    if m.sum()<50: continue
    print(f"{lo:>4}-{hi:<5} {int(m.sum()):>8} {np.median(dv[m]):>6.1f} {np.median(dold[m]):>6.1f} {np.median(dnew[m]):>6.1f} "
          f"{np.median(dv[m]-dold[m]):>+7.1f} {np.median(dv[m]-dnew[m]):>+8.1f} "
          f"{np.mean(np.abs(dv[m]-dold[m])<=5)*100:>4.0f}/{np.mean(np.abs(dv[m]-dnew[m])<=5)*100:<3.0f} "
          f"{np.median(dnew[m]/dold[m]):>6.2f}")
# 全池化
print(f"\n全池化: median(d_vis-d_old)={np.median(dv-dold):+.2f}m  median(d_vis-d_new)={np.median(dv-dnew):+.2f}m")
print(f"        %≤5m old={np.mean(np.abs(dv-dold)<=5)*100:.1f}%  new={np.mean(np.abs(dv-dnew)<=5)*100:.1f}%")
