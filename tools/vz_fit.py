#!/usr/bin/env python3
"""vz_fit.py — verz 黑盒行为学近似拟合 + 与原厂误差评估
输入特征: aEgo(实际减速度), vRel(目标相对速度), dRel(目标距离), vEgo(本车速度)
拟合: 线性回归(最小二乘, numpy)
输出: 训练/验证段的 R2/RMSE/MAE/max/P95 + 按verz深度分桶误差
用法: python3 vz_fit.py ROUTE:SEG ROUTE:SEG --val ROUTE:SEG ...
示例: python3 vz_fit.py 00000002:32 00000002:20 --val 00000004:12 00000004:26
"""
import glob,os,sys,re
sys.path.insert(0,"/data/openpilot")
import numpy as np
from openpilot.tools.lib.logreader import LogReader
DBC="/data/openpilot/opendbc_repo/opendbc/dbc/vw_mlb.dbc"
BASE="/data/media/0/realdata"
def sigs():
    L=open(DBC,encoding="latin-1").read().splitlines()
    s=next(i for i,l in enumerate(L) if l.startswith('BO_ 269 '))
    e=next(i for i in range(s+1,len(L)) if L[i].startswith('BO_ '))
    out={}
    for l in "\n".join(L[s:e]).splitlines():
        m=re.match(r'^\s*SG_ (\w+) : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)',l)
        if m: out[m.group(1)]=(int(m.group(2)),int(m.group(3)),m.group(5)=='-',float(m.group(6)),float(m.group(7)))
    return out
def gs(d,sl,ln,sg,sc=1.0,of=0.0):
    if len(d)<=(sl+ln-1)//8: return 0
    v=0
    for i in range(ln):
        b=(sl+i)//8; bt=(sl+i)%8
        if d[b]&(1<<bt): v|=(1<<i)
    if sg and v&(1<<(ln-1)): v-=(1<<ln)
    return v*sc+of
def load(route,seg):
    p=glob.glob(f"{BASE}/{route}--*--{seg}/rlog.zst")
    if not p: print(f"[{route}-{seg}] 无rlog"); return None
    S=sigs(); rows=[]; cs={}; rt=None
    for m in LogReader(p[0]):
        w=m.which()
        if w=='carState':
            c=m.carState; cs={'a':c.aEgo,'v':c.vEgo}
        elif w=='radarTracks':
            pts=m.radarTracks.points
            if len(pts)>0:
                t0=pts[0]; rt=(t0.dRel,t0.vRel)
        elif w=='can':
            for c in m.can:
                if c.address==269 and c.src==2 and len(c.dat)>=8:
                    d=bytes(c.dat)
                    vz=gs(d,*S['ACC_Verz_anf']); st=int(gs(d,*S['ACC_Status_ACC']))
                    if st==3 and vz<0 and rt is not None:
                        rows.append([cs.get('a',0), rt[1], rt[0], cs.get('v',0), vz])
    return np.array(rows) if rows else None
def metrics(y,yh,label):
    e=y-yh; rmse=np.sqrt((e**2).mean()); mae=np.abs(e).mean()
    denom=((y-y.mean())**2).sum()
    r2=1-((e**2).sum()/denom) if denom>0 else float('nan')
    print(f"  {label}: n={len(y)} RMSE={rmse:.3f} MAE={mae:.3f} max|e|={np.abs(e).max():.3f} "
          f"P95={np.percentile(np.abs(e),95):.3f} R2={r2:+.3f}")
    return np.abs(e)
def bucket_err(y,e):
    for lo,hi,lab in [(0.0,0.5,"0~0.5"),(0.5,1.0,"0.5~1"),(1.0,1.5,"1~1.5"),(1.5,9.0,">1.5")]:
        m=(np.abs(y)>=lo)&(np.abs(y)<hi)
        if m.sum()>0:
            print(f"     |verz|{lab}: n={m.sum()} MAE={e[m].mean():.3f} max={e[m].max():.3f}")
if __name__=='__main__':
    args=sys.argv[1:]
    val_idx=args.index('--val') if '--val' in args else len(args)
    train_specs=args[:val_idx]; val_specs=args[val_idx+1:] if val_idx<len(args) else []
    def split(s): r,_,g=s.rpartition(':'); return r,int(g)
    tr=[load(*split(s)) for s in train_specs]; tr=[t for t in tr if t is not None]
    if not tr: print("无训练数据"); sys.exit(1)
    X=np.vstack([t[:,:4] for t in tr]); y=np.vstack([t[:,4:5] for t in tr]).ravel()
    # 特征: aEgo, vRel, dRel, vEgo, const
    Xd=np.column_stack([X,np.ones(len(X))])
    coef,res,_,_=np.linalg.lstsq(Xd,y,rcond=None)
    print("拟合系数: verz = %.4f*aEgo %+.4f*vRel %+.4f*dRel %+.4f*vEgo %+.4f" % tuple(coef))
    print("--- 训练(合并) ---")
    e=metrics(y,Xd.dot(coef),"all-train")
    bucket_err(y,e)
    for t,s in zip(tr,train_specs):
        if t is None: continue
        Xt=t[:,:4]; yt=t[:,4]
        Xtd=np.column_stack([Xt,np.ones(len(Xt))])
        e=metrics(yt,Xtd.dot(coef),s+"(训练段)")
    if val_specs:
        print("--- 验证(未训练段, 泛化) ---")
        for s in val_specs:
            t=load(*split(s))
            if t is None: continue
            Xv=t[:,:4]; yv=t[:,4]
            Xvd=np.column_stack([Xv,np.ones(len(Xv))])
            yh=Xvd.dot(coef)
            e=metrics(yv,yh,s)
            bucket_err(yv,e)
            # 对比简单模型 verz=1.25*aEgo
            e2=metrics(yv,1.25*Xv[:,0],s+"(简单1.25*aEgo)")
    print("提示: 负误差=拟合比原厂浅(欠刹), 正误差=拟合比原厂深(过刹)")
