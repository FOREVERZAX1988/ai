#!/usr/bin/env python3
import numpy as np, json, os
"""逐 route + 按 zl 分表拟合，并评估同分支 route 间一致性。
输出: 每 route (a,b)、参考距离 d(idx=300)、与池化拟合的中位残差；
     按 zl 分段重复，观察是否 zl 分层后更一致。
"""
ROUTES=['0000006c','00000070','00000071','00000072','00000004','00000002','00000049']
R={r:(np.load(f'/tmp/rows_{r}.npy') if os.path.exists(f'/tmp/rows_{r}.npy') else np.zeros((0,8))) for r in ROUTES}
def prep(X): return X[:,0],np.maximum(X[:,1],5.0),X[:,2],X[:,3],X[:,4],X[:,5]
def gate(X,dt,dlo,dhi,zl=None):
    idx,v,dv,vv,vc,z=prep(X)
    m=(v>=8.0)&(np.abs(vv-vc)<=dt)&(idx>=100)&(idx<=560)&(dv>dlo)&(dv<=dhi)
    if zl is not None: m&= (z==zl)
    return idx[m],v[m],dv[m],z[m]
def dist(a,b,idx,v): return (a*idx+b)*v
def fit_cd(idx,v,dv,kind='l1'):
    if len(idx)<50: return (None,None)
    A=np.vstack([idx,np.ones_like(idx)]).T
    s,_,_,_=np.linalg.lstsq(A,dv/v,rcond=None); p=np.array([float(s[0]),float(s[1])])
    def obj(q):
        ad=np.abs(dv-dist(q[0],q[1],idx,v))
        return {'med':np.median(ad),'l1':np.mean(ad),'p84':np.percentile(ad,84)}[kind]
    f=obj(p); step=np.array([2e-4,0.20])
    for _ in range(300):
        imp=False
        for k in range(2):
            for sg in(+1,-1):
                q=p.copy(); q[k]+=sg*step[k]
                if q[0]<=0: continue
                fq=obj(q)
                if fq<f-1e-12: p=q; f=fq; imp=True
        if not imp:
            step*=0.5
            if step[0]<1e-9: break
    return float(p[0]),float(p[1])
G={}
for r in ROUTES: G[r]=gate(R[r],0.5,0,1e9)
# pooled fit over Sept routes only
pool=np.vstack([R[r] for r in ['0000006c','00000070','00000071','00000072'] if len(R[r])])
gp=gate(pool,0.5,0,1e9)
ap,bp=fit_cd(gp[0],gp[1],gp[2],'l1'); ap2,bp2=fit_cd(gp[0],gp[1],gp[2],'med')
print(f"Pooled Sept(6c,70,71,72): n={len(gp[0])}  l1 a={ap:.6f} b={bp:+.3f} | med a={ap2:.6f} b={bp2:+.3f}")
def med_resid(X,ab):
    idx,v,dv,_,_,_=prep(X)
    m=(v>=8.0)&(np.abs(idx[0]*0)>=0)  # placeholder
    # recompute gate
    gi=gate(X,0.5,0,1e9); 
    if len(gi[0])==0: return None
    e=np.abs(gi[2]-dist(ab[0],ab[1],gi[0],gi[1]))
    return float(np.median(e)),len(gi[0])
print("\n=== 逐 route (G0 l1 拟合) 对比池化拟合 ===")
print(f"{'route':8s} {'n':>6s} {'a':>9s} {'b':>7s} {'d(idx300)':>10s} {'med|Δ|(自fit)':>13s} {'med|Δ|(pool)':>13s}")
for r in ROUTES:
    g=G[r]
    if len(g[0])<50:
        print(f"{r:8s} {len(g[0]):6d} (skip)"); continue
    a,b=fit_cd(g[0],g[1],g[2],'l1')
    d300=(a*300+b)*(30.0)   # at 30 m/s
    selfm=np.median(np.abs(g[2]-dist(a,b,g[0],g[1])))
    poolm=med_resid(R[r],(ap,bp))
    print(f"{r:8s} {len(g[0]):6d} {a:9.6f} {b:+7.3f} {d300:10.1f} {selfm:13.2f} {poolm[0]:13.2f} (n={poolm[1]})")
print("\n=== 按 zl 分段 (仅 Sept routes) ===")
for zl in [2,3,4]:
    gz=gate(pool,0.5,0,1e9,zl)
    if len(gz[0])<30: 
        print(f"  zl={zl}: n={len(gz[0])} (skip)"); continue
    a,b=fit_cd(gz[0],gz[1],gz[2],'l1')
    print(f"  zl={zl}: n={len(gz[0]):6d} a={a:.6f} b={b:+.3f} d(idx300)@30m/s={(a*300+b)*30:.1f}")
