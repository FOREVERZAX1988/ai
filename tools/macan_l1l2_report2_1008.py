#!/usr/bin/env python3
"""L1/L2 影响面精算（DEC 开启且 mode=acc 的实际工作点）"""
import numpy as np, os
from collections import Counter
CACHE="/data/openpilot/ai/tools/cache_l1l2_1008"
segs=[f"00000092--d83e53a0c7--{i}" for i in range(1,16)]
def episodes(mask,t,min_dur=0.0):
    out=[];i=0
    while i<len(mask):
        if mask[i]:
            j=i
            while j+1<len(mask) and mask[j+1]: j+=1
            if t[j]-t[i]>=min_dur: out.append((t[i],t[j]-t[i]))
            i=j+1
        else: i+=1
    return out
R=[]
for s in segs:
    f=f"{CACHE}/{s}.npz"
    if os.path.exists(f):
        z=np.load(f,allow_pickle=True); d={k:z[k] for k in z.files}; d["seg"]=s[-2:]; R.append(d)

print("========== L2 精算（mdes < -0.2 且 src != e2e，DEC active & mode=acc）==========")
rows=[]; tot_f=0; tot_cand=0
for r in R:
    base=(r["enabled"]>0.5)&(r["expmode"]>0.5)
    cand=base&(r["mdes"]<-0.2)&(np.array([s!="e2e" for s in r["src"]]))
    flip=cand&(r["a_plan"]>0.0)            # 现行在加速，L2 会改成刹车
    tot_f+=int(base.sum()); tot_cand+=int(cand.sum())
    rows.append((r["seg"],int(base.sum()),int(cand.sum()),int(flip.sum()),
                 float(np.median(r["a_plan"][flip])) if flip.sum() else 0.0,
                 float(np.median(r["mdes"][flip])) if flip.sum() else 0.0,
                 float(np.median(r["vEgo"][flip])) if flip.sum() else 0.0,
                 float(np.mean(r["lead_present"][flip]>0.5)) if flip.sum() else 0.0,
                 [e[1] for e in episodes(flip,r["t"])]))
print(f"{'seg':>4} {'engage帧':>8} {'候选帧':>7} {'会由加速改判刹车':>16} {'中位a_plan':>10} {'中位mdes':>9} {'中位v':>6} {'有lead':>7} {'最长段s':>8}")
for s,b,c,fl,ap,md,v,lp,eps in rows:
    print(f"{s:>4} {b:>8} {c:>7} {fl:>16} {ap:>10.2f} {md:>9.2f} {v:>6.1f} {100*lp:>6.0f}% {(max(eps) if eps else 0):>8.2f}")
F=np.concatenate([r["enabled"]>0.5 for r in R])
C=np.concatenate([(r["enabled"]>0.5)&(r["mdes"]<-0.2)&(np.array([s!="e2e" for s in r["src"]])) for r in R])
Fl=np.concatenate([(r["enabled"]>0.5)&(r["mdes"]<-0.2)&(np.array([s!="e2e" for s in r["src"]]))&(r["a_plan"]>0.0) for r in R])
V=np.concatenate([r["vEgo"] for r in R]); AP=np.concatenate([r["a_plan"] for r in R])
MD=np.concatenate([r["mdes"] for r in R]); LP=np.concatenate([r["lead_present"] for r in R])
print(f"\nengage 帧 {int(F.sum())}；L2 候选 {int(C.sum())} ({100*C.sum()/F.sum():.1f}% of engage)；其中会被改判刹车 {int(Fl.sum())} ({100*Fl.sum()/F.sum():.2f}%)")
print(f"  改判刹车的代价: 中位 Δa = {np.median(MD[Fl]-AP[Fl]):+.2f} m/s², p90 = {np.percentile(MD[Fl]-AP[Fl],90):+.2f} m/s²")
for lo,hi,nm in [(0,4,"<4m/s"),(4,10,"4-10"),(10,60,">10m/s")]:
    s=Fl&(V>=lo)&(V<hi)
    print(f"  {nm}: {int(s.sum())} 帧, 其中无 lead {int((s&(LP<0.5)).sum())} 帧, 中位 v={np.median(V[s]) if s.sum() else 0:.1f}, "
          f"中位 Δ={np.median(MD[s]-AP[s]) if s.sum() else 0:+.2f}, 最长段 {max([e[1] for r in R for e in episodes((r['enabled']>0.5)&(r['mdes']<-0.2)&(np.array([x!='e2e' for x in r['src']]))&(r['a_plan']>0)&(r['vEgo']>=lo)&(r['vEgo']<hi),r['t'])]+[0]):.2f}s")

print("\n========== L1 精算（lead 已消失 + prob∈[0.25,0.5) + 0.5s 内曾有 ≥0.5）==========")
tot=0; res=[]
for r in R:
    t=r["t"]; p=r["prob"]; base=(r["enabled"]>0.5)&(r["lead_present"]<0.5)
    recent=np.zeros(len(p),bool); last=-9e9
    for i in range(len(p)):
        if p[i]>=0.5: last=t[i]
        recent[i]=(t[i]-last)<=0.5
    m=base&(p>=0.25)&(p<0.5)&recent
    if m.sum():
        tot+=int(m.sum())
        hv=r["vEgo"][m]
        # 死推距离 vs 模型自己当帧给出的 x（低置信但仍是模型读数）
        vis=r["vis_x"][m]-1.52
        res.append((r["seg"],int(m.sum()),float(np.median(hv)),float(np.mean(p[m])),np.median(vis)))
print(f"候选帧合计 {tot} / engage {int(F.sum())} = {100*tot/F.sum():.3f}%")
for row in res: print(f"  seg{row[0]:>3} 帧{row[1]:>3} 中位v={row[2]:.1f} 中位prob={row[3]:.2f} 模型当帧x(m)中位={row[4]:.1f}")
for lo,hi,nm in [(0,4,"<4m/s"),(4,10,"4-10"),(10,60,">10m/s")]:
    n=0; eps=[]
    for r in R:
        t=r["t"]; p=r["prob"]; base=(r["enabled"]>0.5)&(r["lead_present"]<0.5)&(r["vEgo"]>=lo)&(r["vEgo"]<hi)
        recent=np.zeros(len(p),bool); last=-9e9
        for i in range(len(p)):
            if p[i]>=0.5: last=t[i]
            recent[i]=(t[i]-last)<=0.5
        m=base&(p>=0.25)&(p<0.5)&recent; n+=int(m.sum()); eps+=[e[1] for e in episodes(m,t)]
    print(f"  {nm}: {n} 帧, {len(eps)} 段, 最长 {max(eps) if eps else 0:.2f}s, >0.5s {sum(1 for x in eps if x>=0.5)}")

print("\n========== 车库片段(seg2 t≈166-170) 逐帧，看 L1 会不会接住 ==========")
r=[x for x in R if x["seg"]=="-2"][0]
idx=np.where((r["t"]>=166.0)&(r["t"]<=170.2))[0]
print(f"{'t':>7} {'v':>5} {'prob':>5} {'lead':>5} {'mdes':>6} {'a_plan':>7} {'src':>7}")
for i in idx:
    print(f"{r['t'][i]:7.2f} {r['vEgo'][i]:5.2f} {r['prob'][i]:5.2f} {int(r['lead_present'][i]>0.5):5d} {r['mdes'][i]:6.2f} {r['a_plan'][i]:7.2f} {r['src'][i]:>7}")
