#!/usr/bin/env python3
"""逐 route 拟合 B1 系数，检查『同一纵向分支下各 route 拟合系数是否一致』。
口径: /tmp/rows_<route>.npy [idx,v_use,d_vis,v_vis,v_can,zl,d_old,d_new]
门控 G0: v>=8 & |v_vis-v_can|<=0.5 & 100<=idx<=560 & d_vis>0
G1(高可信): v>=8 & |v_vis-v_can|<=0.20 & 100<=idx<=560 & 5<=d_vis<=80
拟合: 距离域 mean|Δ|(l1) / med|Δ| / t域RMS
"""
import numpy as np, json, os
ROUTES=['0000006c','0000006d','00000070','00000071','00000072','00000004','00000002','00000049']
R={r:(np.load(f'/tmp/rows_{r}.npy') if os.path.exists(f'/tmp/rows_{r}.npy') else np.zeros((0,8))) for r in ROUTES}
def prep(X): return X[:,0],np.maximum(X[:,1],5.0),X[:,2],X[:,3],X[:,4]
def gate(X,dt,dlo,dhi):
    idx,v,dv,vv,vc=prep(X)
    m=(v>=8.0)&(np.abs(vv-vc)<=dt)&(idx>=100)&(idx<=560)&(dv>dlo)&(dv<=dhi)
    return idx[m],v[m],dv[m]
def dist(a,b,idx,v): return (a*idx+b)*v
def fit_cd(idx,v,dv,kind):
    A=np.vstack([idx,np.ones_like(idx)]).T
    s,_,_,_=np.linalg.lstsq(A,dv/v,rcond=None)
    p=np.array([float(s[0]),float(s[1])])
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
def fit_lsq(idx,v,dv):
    A=np.vstack([idx,np.ones_like(idx)]).T
    s,_,_,_=np.linalg.lstsq(A,dv/v,rcond=None)
    return float(s[0]),float(s[1])
print("route      n_G0   a(G0,l1)   b(G0,l1)   a(G1,l1)   b(G1,l1)   n_G1")
out={}
for r in ROUTES:
    g0=gate(R[r],0.5,0,1e9); g1=gate(R[r],0.20,5,80)
    if len(g0[0])<50 and len(g1[0])<50:
        print(f"{r}   nG0={len(g0[0]):6d} nG1={len(g1[0]):6d} (skip)")
        out[r]={'nG0':int(len(g0[0])),'nG1':int(len(g1[0]))}
        continue
    a0,b0=fit_cd(*g0,'l1'); a0q,b0q=fit_cd(*g0,'med')
    a1,b1=fit_cd(*g1,'l1')
    print(f"{r}  {len(g0[0]):6d}  {a0:.6f} {b0:+7.3f}  {a1:.6f} {b1:+7.3f}  {len(g1[0]):6d}")
    out[r]={'nG0':int(len(g0[0])),'G0_l1':[a0,b0],'G0_med':[a0q,b0q],'nG1':int(len(g1[0])),'G1_l1':[a1,b1]}
json.dump(out,open('/tmp/fit_perroute_0912.json','w'),indent=1)
