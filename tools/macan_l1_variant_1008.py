#!/usr/bin/env python3
"""L1 备选实现：'低置信但距离自洽' 而非固定 prob 门"""
import numpy as np, os
CACHE="/data/openpilot/ai/tools/cache_l1l2_1008"
segs=[f"00000092--d83e53a0c7--{i}" for i in range(1,16)]
R=[]
for s in segs:
    f=f"{CACHE}/{s}.npz"
    if os.path.exists(f):
        z=np.load(f,allow_pickle=True); d={k:z[k] for k in z.files}; d["tr"]=d["t"]-d["t"][0]; d["seg"]=s[-2:]; R.append(d)

def sim(r, hold=0.6, prob_min=0.15, skip=0.15, rel=0.20, absm=2.0, use_x=True):
    t=r["t"]; last_conf=-9e9; last_d=np.nan; resc=np.zeros(len(t),bool); alive=np.zeros(len(t),bool); dist=[]
    for i in range(len(t)):
        pres=r["lead_present"][i]>0.5
        ok=False
        if not pres and (t[i]-last_conf)<=hold and np.isfinite(last_d):
            x=r["vis_x"][i]-1.52
            if r["prob"][i]>=prob_min and np.isfinite(x):
                if use_x:
                    if abs(x-last_d)<=max(absm, rel*last_d): ok=True
                else:
                    if r["prob"][i]>=skip: ok=True
        alive[i]=pres or ok; resc[i]=(not pres) and ok
        if pres and np.isfinite(r["d_fus"][i]):
            if r["d_fus"][i]>0.1: last_d=r["d_fus"][i]; last_conf=t[i]
    return resc,alive

for use_x,tag in [(True,"自洽式(prob>=0.15 且 |x-d_last|<=max(2,20%))"),(False,"纯门式(prob>=0.25, hold0.6)")]:
    resc_t=hi=lo=allf=0; cov=tot=0
    for r in R:
        resc,alive=sim(r,use_x=use_x)
        resc_t+=int(resc.sum()); allf+=len(r["t"])
        hi+=int((resc&(r["vEgo"]>10)).sum()); lo+=int((resc&(r["vEgo"]<4)&(r["enabled"]>0.5)).sum())
        if r["seg"]=="-2":
            m=(r["tr"]>=46.8)&(r["tr"]<=48.3); cov+=int((alive&m).sum()); tot+=int(m.sum())
    print(f"{tag}: 车库窗口 {cov}/{tot}; 全线救回 {resc_t} ({100*resc_t/allf:.2f}%); 高速>10 救回 {hi}; 低速<4 救回 {lo}")

print("\n=== 自洽式：救回帧的 上次融合距离 vs 当帧模型 x ===")
for r in R:
    resc,alive=sim(r,True)
    for i in np.where(resc)[0]:
        pass
    # 打印高速与低速若干
    idx=np.where(resc)[0]
    if len(idx):
        print(f"  seg{r['seg']}: {len(idx)} 帧, v 中位 {np.median(r['vEgo'][idx]):.1f}, prob 中位 {np.median(r['prob'][idx]):.2f}, "
              f"当帧x 中位 {np.median(r['vis_x'][idx]-1.52):.1f}")
