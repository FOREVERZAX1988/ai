import numpy as np, os
ROUTES=['0000006c','0000006d','00000070','00000071','00000072','00000002','00000003','00000004','00000049']
NEW=set(['0000006c','0000006d','00000070','00000071','00000072'])
def load(r):
    p=f'/tmp/rows_{r}.npy'
    return np.load(p) if os.path.exists(p) else np.zeros((0,8))
def team(X):  # (idx,v_use,d_vis,v_vis,v_can,zl)
    return X[:,0],np.maximum(X[:,1],5.0),X[:,2],X[:,3],X[:,4],X[:,5]
print(f"{'route':9s} {'rows':>6s} {'zl%3':>5s} {'zl%4':>5s} {'G0n':>6s} {'a':>9s} {'b':>8s} {'med|del|':>8s} {'%<=4m':>6s}  (拟合口径: G0, t=a*idx+b, 距离=a*idx*v)")
for r in ROUTES:
    X=load(r)
    idx,v,dv,vv,vc,zl=team(X)
    # zl distribution of bus2 (col5)
    zl=zl.astype(int)
    p3=100*np.mean(zl==3) if len(zl) else float('nan')
    p4=100*np.mean(zl==4) if len(zl) else float('nan')
    # G0 gate
    m=(v>=8.0)&(np.abs(vv-vc)<=0.5)&(idx>=100)&(idx<=560)&(dv>0)
    ii,vv2,dd=idx[m],v[m],dv[m]
    n=len(ii)
    if n<200:
        print(f"{r:9s} {len(X):6d} {p3:5.1f} {p4:5.1f} {n:6d}  (样本不足,跳过)")
        continue
    A=np.vstack([ii,np.ones_like(ii)]).T
    s,_,_,_=np.linalg.lstsq(A,dd/vv2,rcond=None)
    a,b=s[0],s[1]
    e=np.abs(dd-(a*ii+b)*vv2)
    med=np.median(e) if len(e) else float('nan')
    p4m=100*np.mean(e<=4) if len(e) else float('nan')
    tag='NEW' if r in NEW else 'OLD'
    print(f"{r:9s} {len(X):6d} {p3:5.1f} {p4:5.1f} {n:6d} {a:9.6f} {b:+8.4f} {med:8.2f} {p4m:6.1f}  [{tag}]")
