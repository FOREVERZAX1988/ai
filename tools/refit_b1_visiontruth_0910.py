#!/usr/bin/env python3
"""B1 单表重标定：以『视野清晰(视觉可靠)时的视觉距离』为准，最小化 视觉−雷达 距离差。
口径: /tmp/rows_<route>.npy [idx,v_use,d_vis,v_vis,v_can,zl,d_old,d_new]
G0(基线干净同目标): v>=8 & |v_vis-v_can|<=0.5 & 100<=idx<=560
G1(视觉高可信代理): G0 & |v_vis-v_can|<=0.20 & 5<=d_vis<=80
目标: t域RMS(现行B1口径) / 距离域 med|Δ| / mean|Δ| / P84|Δ|   （纯 numpy 坐标下降）
"""
import numpy as np, json, os
OLD=['00000002','00000003','00000004','00000049']; NEW=['00000071','00000072']; ROUTES=OLD+NEW
R={r:(np.load(f'/tmp/rows_{r}.npy') if os.path.exists(f'/tmp/rows_{r}.npy') else np.zeros((0,8))) for r in ROUTES}
ALL=np.vstack([R[r] for r in ROUTES]); OLDX=np.vstack([R[r] for r in OLD]); NEWX=np.vstack([R[r] for r in NEW])
def prep(X):
    return X[:,0],np.maximum(X[:,1],5.0),X[:,2],X[:,3],X[:,4]
def gate(X,dt=0.5,dlo=0.0,dhi=1e9):
    idx,v,dv,vv,vc=prep(X); m=(v>=8.0)&(np.abs(vv-vc)<=dt)&(idx>=100)&(idx<=560)&(dv>dlo)&(dv<=dhi)
    return idx[m],v[m],dv[m]
G={'G0池化':gate(ALL),'G0旧分支':gate(OLDX),'G0新分支':gate(NEWX),
   'G1池化':gate(ALL,0.20,5.0,80.0),'G1旧分支':gate(OLDX,0.20,5.0,80.0),'G1新分支':gate(NEWX,0.20,5.0,80.0)}
print("=== 样本量 ==="); [print(f"  {k:9s} n={len(v[0]):6d}") for k,v in G.items()]
def dist(a,b,idx,v): return (a*idx+b)*v
def stats(idx,v,dv,a,b):
    d=dist(a,b,idx,v); e=dv-d; ad=np.abs(e); r=ad/np.maximum(d,1.0)
    return float(np.median(e)),float(np.median(ad)),100*float(np.mean(ad<=5)),100*float(np.mean(r>0.30)),float(np.mean(ad))
def fit_lsq(idx,v,dv):
    A=np.vstack([idx,np.ones_like(idx)]).T; s,_,_,_=np.linalg.lstsq(A,dv/v,rcond=None); return float(s[0]),float(s[1])
def obj(idx,v,dv,p,kind):
    ad=np.abs(dv-dist(p[0],p[1],idx,v))
    return {'med':np.median(ad),'l1':np.mean(ad),'p84':np.percentile(ad,84)}[kind]
def fit_cd(idx,v,dv,kind,a0=None,b0=None):
    if a0 is None: a0,b0=fit_lsq(idx,v,dv)
    p=np.array([a0,b0],dtype=float); f=obj(idx,v,dv,p,kind)
    step=np.array([2e-4,0.20])
    for _ in range(300):
        improved=False
        for k in range(2):
            for s in (+1,-1):
                q=p.copy(); q[k]+=s*step[k]
                if q[0]<=0: continue
                fq=obj(idx,v,dv,q,kind)
                if fq<f-1e-12: p,f,fq=q,fq,None; improved=True
        if not improved:
            step*=0.5
            if step[0]<1e-9: break
    return float(p[0]),float(p[1])
CANDS={}
for tag,g in (('G0池化','G0池化'),('G1池化','G1池化')):
    idx,v,dv=G[g]
    CANDS[(tag,'A_t域RMS(现行B1口径)')]=fit_lsq(idx,v,dv)
    for kind,name in (('med','B_距离域med|Δ|'),('l1','C_距离域mean|Δ|'),('p84','D_距离域P84|Δ|')):
        CANDS[(tag,name)]=fit_cd(idx,v,dv,kind)
CANDS[('固定','E_现行代码B1')]=(0.008969,0.332); CANDS[('固定','F_旧153表')]=(0.008951,0.1625)
print("\n=== 候选系数 (t = a*idx + b) ===")
for (g,n),(a,b) in CANDS.items():
    if g!='固定': print(f"  [{g}] {n:22s} a={a:.6f} b={b:+.4f}")
print("\n=== 在 G0池化 基线集上的表现（按 med|Δ| 排序）===")
idx,v,dv=G['G0池化']; rows=[]
for (g,n),(a,b) in CANDS.items():
    med,mad,p5,r30,mn=stats(idx,v,dv,a,b); rows.append((mad,med,p5,r30,n,g,(a,b)))
for mad,med,p5,r30,n,g,ab in sorted(rows):
    print(f"  {n:22s}[{g}] med(vis-rad)={med:+6.2f}m med|Δ|={mad:5.2f}m %<=5m={p5:5.1f}% ratio>30%={r30:5.1f}%")
print("\n=== 最优候选 vs 现行B1：分支内 / 视觉高可信集 ===")
bestname=min(rows)[4]; bestab=CANDS[('G0池化',bestname)] if ('G0池化',bestname) in CANDS else CANDS[('G1池化',bestname)]
print(f"  best='{bestname}' a={bestab[0]:.6f} b={bestab[1]:+.4f}")
for g in ('G0池化','G0旧分支','G0新分支','G1池化','G1旧分支','G1新分支'):
    idx,v,dv=G[g]
    for lab,(a,b) in (('现行B1',(0.008969,0.332)),('重拟合',bestab),('旧153表',(0.008951,0.1625))):
        med,mad,p5,r30,_=stats(idx,v,dv,a,b)
        print(f"  {g:9s} {lab:7s} n={len(idx):6d} med={med:+6.2f} med|Δ|={mad:5.2f} %<=5m={p5:5.1f} ratio>30%={r30:5.1f}")
print("\n=== 视觉可信度(速度一致度) vs 距离差 (现行B1) ===")
idx,v,dv,vv,vc=prep(ALL); m0=(v>=8.0)&(idx>=100)&(idx<=560)&(dv>0)&(np.abs(vv-vc)<=1.5)
dd=dist(0.008969,0.332,idx[m0],v[m0]); e=np.abs(dv[m0]-dd); dvp=np.abs(vv[m0]-vc[m0])
for lo,hi in [(0,0.1),(0.1,0.2),(0.2,0.35),(0.35,0.5),(0.5,0.8),(0.8,1.5)]:
    s=(dvp>=lo)&(dvp<hi)
    if s.sum()>50: print(f"  |v_vis-v_can|∈[{lo},{hi}) n={s.sum():6d} med|Δd|={np.median(e[s]):5.2f}m %<=5m={100*np.mean(e[s]<=5):5.1f}%")
json.dump({f'{g}|{n}':list(v) for (g,n),v in CANDS.items() if g!='固定'},open('/tmp/refit_b1.json','w'),indent=1)
