#!/usr/bin/env python3
"""mom_fit_feat.py — 原厂mom拟合：特征对比实验（v/a vs 加前车dRel/vRel）
回答: 引入雷达前车数据能否降低拟合误差？
用法: python3 mom_fit_feat.py --train 00000004:7 00000002:32 --val 00000004:6 00000002:20 00000002:21
输出: 特征集A/B的训练/验证 RMSE·MAE·R2 对比
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
    S=sigs(); rows=[]; cs={}
    for m in LogReader(p[0]):
        w=m.which()
        if w=='carState':
            c=m.carState; cs={'v':c.vEgo,'a':c.aEgo}
        elif w=='radarTracks':
            pts=m.radarTracks.points
            if len(pts)>0:
                t0=pts[0]
                cs['d']=float(t0.dRel); cs['vr']=float(t0.vRel)
        elif w=='can':
            for c in m.can:
                if c.address==269 and c.src==2 and len(c.dat)>=8:
                    d=bytes(c.dat)
                    mom=gs(d,*S['ACC_Momentenanforderung']); st=int(gs(d,*S['ACC_Status_ACC']))
                    vz=gs(d,*S['ACC_Verz_anf'])
                    if st==3 and 'v' in cs and 'd' in cs:
                        rows.append([cs['v'],cs['a'],cs['d'],cs['vr'],mom,vz])
    return np.array(rows) if rows else None
def main():
    args=sys.argv[1:]
    if '--train' in args: args.remove('--train')
    vi=args.index('--val') if '--val' in args else len(args)
    tr=args[:vi]; val=args[vi+1:] if vi<len(args) else []
    def split(s): r,_,g=s.rpartition(':'); return r,int(g)
    T=None
    for s in tr:
        t=load(*split(s))
        if t is None: continue
        T=t if T is None else np.vstack([T,t])
    if T is None: print("无训练数据"); sys.exit(1)
    T=T[T[:,5]>=-0.02]   # 力矩生效帧（同mom_fit口径）
    if len(T)<100: print("帧不足"); sys.exit(1)
    print(f"训练帧 {len(T)} | 列: v a dRel vRel mom verz")
    # 特征集A: v,a | 特征集B: v,a,dRel,vRel
    XA=np.column_stack([np.ones(len(T)),T[:,0],T[:,1]])
    XB=np.column_stack([np.ones(len(T)),T[:,0],T[:,1],T[:,2],T[:,3]])
    y=T[:,4]
    for name,X in [("A(v,a)",XA),("B(v,a,dRel,vRel)",XB)]:
        w,_,_,_=np.linalg.lstsq(X,y,rcond=None)
        yh=X@w; e=y-yh
        r2=1-((e**2).sum()/((y-y.mean())**2).sum())
        print(f"[训练][{name}] RMSE={np.sqrt((e**2).mean()):.1f} MAE={np.abs(e).mean():.1f} max={np.abs(e).max():.1f} R2={r2:+.3f}")
        for lo,hi,lab in [(0,5,"0-5m/s"),(5,10,"5-10"),(10,15,"10-15"),(15,20,"15-20"),(20,30,"20-30")]:
            mm=(T[:,0]>=lo)&(T[:,0]<hi)
            if mm.sum()>10: print(f"     v{lab}: n={mm.sum()} MAE={np.abs(e[mm]).mean():.1f}")
        if name.startswith("B"):
            print(f"   B系数: 截距{w[0]:.1f} v{w[1]:.2f} a{w[2]:.2f} dRel{w[3]:.3f} vRel{w[4]:.2f}")
    for s in val:
        t=load(*split(s))
        if t is None: continue
        t=t[t[:,5]>=-0.02]
        if len(t)<10: continue
        for name,Xc in [("A(v,a)",np.column_stack([np.ones(len(t)),t[:,0],t[:,1]])),
                        ("B(v,a,dRel,vRel)",np.column_stack([np.ones(len(t)),t[:,0],t[:,1],t[:,2],t[:,3]]))]:
            w,_,_,_=np.linalg.lstsq(XA if name.startswith("A") else XB, y, rcond=None)  # 用训练权重
            yh=Xc@w; e=t[:,4]-yh
            print(f"[验证 {s}][{name}] n={len(t)} RMSE={np.sqrt((e**2).mean()):.1f} MAE={np.abs(e).mean():.1f} max={np.abs(e).max():.1f}")
if __name__=="__main__": main()
