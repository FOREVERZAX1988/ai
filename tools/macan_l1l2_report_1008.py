#!/usr/bin/env python3
import numpy as np, glob, os
from collections import Counter
CACHE="/data/openpilot/ai/tools/cache_l1l2_1008"

def episodes(mask, t, min_dur=0.0):
    out=[]; i=0
    while i<len(mask):
        if mask[i]:
            j=i
            while j+1<len(mask) and mask[j+1]: j+=1
            if t[j]-t[i]>=min_dur: out.append((t[i],t[j]-t[i]))
            i=j+1
        else: i+=1
    return out
segs=[f"00000092--d83e53a0c7--{i}" for i in range(1,16)]
R=[]
for s in segs:
    f=f"{CACHE}/{s}.npz"
    if not os.path.exists(f): continue
    z=np.load(f,allow_pickle=True); d={k:z[k] for k in z.files}
    d["seg"]=s[-2:]; R.append(d)
tot=sum(len(r["t"]) for r in R); dur=sum(r["t"][-1]-r["t"][0] for r in R)
eng=sum(float(np.mean(r["enabled"]))*(len(r["t"])) for r in R)
print(f"segments {len(R)}  modelV2帧 {tot}  时长 {dur:.0f}s  engage帧占比 {100*eng/tot:.1f}%")
print("src 分布:", Counter(np.concatenate([r['src'] for r in R]).tolist()).most_common(8))
print("experimentalMode:", {float(k):int(v) for k,v in zip(*np.unique(np.concatenate([r['expmode'] for r in R]),return_counts=True))})

# ---------- L2 ----------
print("\n===== L2: mdes<-0.2 且 src!=e2e（现行不放行 / L2 会新放行）=====")
allT=[]; 
for r in R:
    m=(r["enabled"]>0.5)&(r["mdes"]<-0.2)&(np.array([s!="e2e" for s in r["src"]]))
    if m.sum()==0: continue
    v=r["vEgo"][m]; md=r["mdes"][m]; lp=r["lead_present"][m]; ap=r["a_plan"][m]
    src=Counter(r["src"][m].tolist())
    eps=episodes(m,r["t"])
    allT.append((r["seg"],int(m.sum()),len(eps),float(np.median(eps and [e[1] for e in eps] or [0])),
                 float(np.median(v)),float(np.mean(lp)),float(np.median(md)),float(np.median(ap)),src))
print(f"{'seg':>4} {'帧':>5} {'段':>4} {'中位时长':>8} {'中位v':>6} {'有lead':>7} {'中位mdes':>8} {'中位a_plan':>10}  src")
for row in allT:
    print(f"{row[0]:>4} {row[1]:>5} {row[2]:>4} {row[3]:>8.2f} {row[4]:>6.1f} {100*row[5]:>6.0f}% {row[6]:>8.2f} {row[7]:>10.2f}  {dict(row[8])}")
M=np.concatenate([( (r["enabled"]>0.5)&(r["mdes"]<-0.2)&(np.array([s!="e2e" for s in r["src"]])) ) for r in R])
md=np.concatenate([r["mdes"] for r in R]); v=np.concatenate([r["vEgo"] for r in R])
lp=np.concatenate([r["lead_present"] for r in R]); en=np.concatenate([r["enabled"] for r in R])
print(f"\n合计候选帧 {int(M.sum())} ({100*M.mean():.2f}% of all)  engage 内 {100*M.sum()/max((en>0.5).sum(),1):.2f}%")
print("  mdes 分位:", np.round(np.percentile(md[M],[5,25,50,75,95]),2))
print("  '空路'子集(无lead & v>5):", int(((M)&(lp<0.5)&(v>5)).sum()), "帧")
print("  '空路'子集(无lead & v>10):", int(((M)&(lp<0.5)&(v>10)).sum()), "帧")
print("  有lead子集:", int((M&(lp>0.5)).sum()), "帧")
sub=M&(lp<0.5)&(v>5)
if sub.sum():
    print("  空路 mdes 分位:", np.round(np.percentile(md[sub],[5,25,50,75,95]),2), " 中位v=",round(float(np.median(v[sub])),1))
for vlo,vhi,name in [(0,4,"低速<4m/s"),(4,10,"4-10"),(10,60,">10m/s")]:
    s=M&(v>=vlo)&(v<vhi); s2=s&(lp<0.5)
    print(f"  {name}: 候选 {int(s.sum())} 帧, 其中无lead {int(s2.sum())} 帧 ({100*s2.sum()/max(s.sum(),1):.0f}%)")

print("\n===== L2 逐段最长候选段（>0.5s）=====")
for r in R:
    m=(r["enabled"]>0.5)&(r["mdes"]<-0.2)&(np.array([s!="e2e" for s in r["src"]]))
    for t0,du in sorted(episodes(m,r["t"]),key=lambda e:-e[1])[:2]:
        if du<0.5: continue
        i0=int(np.searchsorted(r["t"],t0)); i1=int(np.searchsorted(r["t"],t0+du))
        sl=slice(i0,i1+1)
        print(f"  seg{r['seg']} t={t0:.1f} 时长{du:.2f}s v={np.median(r['vEgo'][sl]):.1f} "
              f"lead={100*np.mean(r['lead_present'][sl]>0.5):.0f}% mdes[{np.min(r['mdes'][sl]):+.2f},{np.max(r['mdes'][sl]):+.2f}] "
              f"a_plan[{np.min(r['a_plan'][sl]):+.2f},{np.max(r['a_plan'][sl]):+.2f}] src={Counter(r['src'][sl].tolist())}")

# ---------- L1 ----------
print("\n===== L1: prob∈[0.25,0.5) 且 0.5s 内曾有 prob>=0.5（L1 会 hold）=====")
for vlo,vhi,name in [(0,4,"低速<4m/s"),(4,10,"4-10m/s"),(10,60,">10m/s")]:
    tot_c=0; hold=0; eps_all=[]
    for r in R:
        p=r["prob"]; t=r["t"]; m0=(r["vEgo"]>=vlo)&(r["vEgo"]<vhi)&(r["enabled"]>0.5)
        recent=np.zeros(len(p),bool)
        last=-9e9
        for i in range(len(p)):
            if p[i]>=0.5: last=t[i]
            recent[i]=(t[i]-last)<=0.5
        m=m0&(p>=0.25)&(p<0.5)&recent
        tot_c+=int(m0.sum()); hold+=int(m.sum())
        eps_all+= [e[1] for e in episodes(m,t,min_dur=0.0)]
    if eps_all:
        print(f"  {name}: 帧 {tot_c}, L1 会 hold {hold} ({100*hold/max(tot_c,1):.3f}%), 段数 {len(eps_all)}, "
              f"时长 中位{np.median(eps_all):.3f}s p90={np.percentile(eps_all,90):.3f}s max={max(eps_all):.2f}s, "
              f">0.5s 段 {sum(1 for x in eps_all if x>0.5)}")
    else:
        print(f"  {name}: 帧 {tot_c}, 无候选")

print("\n===== 现网基准：prob>=0.5 但 lead_present=False（视觉已捕捉、融合层未生效的帧）=====")
for vlo,vhi,name in [(0,4,"<4m/s"),(4,10,"4-10"),(10,60,">10m/s")]:
    c=0; tt=0
    for r in R:
        m0=(r["vEgo"]>=vlo)&(r["vEgo"]<vhi)&(r["enabled"]>0.5)
        tt+=int(m0.sum()); c+=int((m0&(r["prob"]>=0.5)&(r["lead_present"]<0.5)).sum())
    print(f"  {name}: {c} / {tt} ({100*c/max(tt,1):.2f}%)")
