#!/usr/bin/env python3
"""ar_verz_model.py — verz 一阶AR状态机模型（原厂verz预测）
模型: verz[t] = a*verz[t-1] + b0 + b1*aEgo + b2*vRel + b3*dRel + b4*vEgo
两种评估:
  TF  = teacher-forcing（用真实verz[t-1]）→ 模拟"跟随原厂读实时值"场景
  FRE = free-running（用预测verz[t-1]递推）→ 模拟"完全脱离原厂自己算"
用法: python3 ar_verz_model.py --fit 00000004:12 00000004:26 --eval 00000002
"""
import glob,os,sys,re
sys.path.insert(0,"/data/openpilot")
import numpy as np
from multiprocessing import Pool
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
    if not p: return None
    S=sigs(); rows=[]; cs={}; rt=None
    for m in LogReader(p[0]):
        w=m.which()
        if w=='carState':
            c=m.carState; cs={'v':float(c.vEgo),'a':float(c.aEgo)}
        elif w=='radarTracks':
            pts=m.radarTracks.points
            if len(pts)>0:
                t0=pts[0]; rt=(float(t0.dRel),float(t0.vRel))
        elif w=='can':
            for c in m.can:
                if c.address==269 and c.src==2 and len(c.dat)>=8:
                    d=bytes(c.dat)
                    vz=gs(d,*S['ACC_Verz_anf']); st=int(gs(d,*S['ACC_Status_ACC']))
                    if st==3:
                        rows.append([vz, cs.get('a',0),
                                     rt[1] if rt else 0, rt[0] if rt else 0,
                                     cs.get('v',0)])
    return np.array(rows) if len(rows)>30 else None
def train_ar(segments):
    Xl=[]; yl=[]
    for r,s in segments:
        t=load(r,s)
        if t is None or len(t)<5: continue
        Xv=np.column_stack([t[:-1,0], t[:-1,1], t[:-1,2], t[:-1,3], t[:-1,4], np.ones(len(t)-1)])
        Xl.append(Xv); yl.append(t[1:,0])
    if not Xl: return None
    X=np.vstack(Xl); y=np.concatenate(yl)
    coef=np.linalg.lstsq(X,y,rcond=None)[0]
    e=y-X@coef
    return coef, np.sqrt((e**2).mean()), np.abs(e).mean(), len(y)
def eval_seg(arg):
    route,seg,coef=arg
    t=load(route,seg)
    if t is None: return None
    n=len(t)
    Xtf=np.column_stack([t[:-1,0], t[:-1,1], t[:-1,2], t[:-1,3], t[:-1,4], np.ones(n-1)])
    ytf=Xtf@coef
    e_tf=t[1:,0]-ytf
    yf=np.zeros(n); yf[0]=t[0,0]
    for i in range(1,n):
        yf[i]=coef[0]*yf[i-1]+coef[1]*t[i,1]+coef[2]*t[i,2]+coef[3]*t[i,3]+coef[4]*t[i,4]+coef[5]
    e_fr=t[1:,0]-yf[1:]
    dec=t[1:,0]<0
    _etf=e_tf[dec]; _efr=e_fr[dec]
    r=dict(seg=int(seg),n=n,
           tf_n=int(dec.sum()), tf_ss=float((_etf**2).sum()), tf_mae=float(np.abs(_etf).sum()), tf_max=float(np.abs(_etf).max()) if len(_etf) else 0.0,
           fr_n=int(dec.sum()), fr_ss=float((_efr**2).sum()), fr_mae=float(np.abs(_efr).sum()),
           tf_n0=n-1, tf_ss0=float((e_tf**2).sum()), tf_mae0=float(np.abs(e_tf).sum()),
           fr_ss0=float((e_fr**2).sum()), fr_mae0=float(np.abs(e_fr).sum()))
    return r
def main():
    args=sys.argv[1:]
    fi=args.index('--fit') if '--fit' in args else -1
    ei=args.index('--eval') if '--eval' in args else -1
    fit_specs=args[fi+1:ei] if fi>=0 else []
    eval_specs=args[ei+1:] if ei>=0 else []
    def split(s): r,_,g=s.rpartition(':'); return r,int(g)
    fit_segs=[split(s) for s in fit_specs]
    coef,trmse,trmae,trn=train_ar(fit_segs)
    if coef is None: print("无训练数据"); sys.exit(1)
    print(f"训练 {fit_specs}: n={trn} 拟合RMSE={trmse:.3f} MAE={trmae:.3f}")
    print(f"AR系数: verz[t-1]={coef[0]:.3f} aEgo={coef[1]:+.3f} vRel={coef[2]:+.3f} dRel={coef[3]:+.3f} vEgo={coef[4]:+.3f} 截距={coef[5]:+.2f}", flush=True)
    route=eval_specs[0]
    segs=[os.path.basename(os.path.dirname(p)).split('--')[-1] for p in sorted(glob.glob(f"{BASE}/{route}--*--*/rlog.zst"))]
    print(f"评估 {route}: {len(segs)} 段 (并行4)", flush=True)
    with Pool(4) as pool:
        res=[r for r in pool.map(eval_seg,[(route,s,coef) for s in segs]) if r is not None]
    tf_n=sum(r['tf_n'] for r in res); tf_ss=sum(r['tf_ss'] for r in res); tf_mae=sum(r['tf_mae'] for r in res)
    fr_n=sum(r['fr_n'] for r in res); fr_ss=sum(r['fr_ss'] for r in res); fr_mae=sum(r['fr_mae'] for r in res)
    n0=sum(r['tf_n0'] for r in res); ss0=sum(r['tf_ss0'] for r in res); mae0=sum(r['tf_mae0'] for r in res)
    fr0=sum(r['fr_ss0'] for r in res); frmae0=sum(r['fr_mae0'] for r in res)
    print(f"\n===== {route} 全route (有效段 {len(res)}) AR模型 vs 静态公式(RMSE1.29) =====")
    print(f"[减速帧] TF(用真实前值): n={tf_n} RMSE={np.sqrt(tf_ss/tf_n):.3f} MAE={tf_mae/tf_n:.3f} max={max(r['tf_max'] for r in res):.3f}")
    print(f"[减速帧] FRE(自递推):   n={fr_n} RMSE={np.sqrt(fr_ss/fr_n):.3f} MAE={fr_mae/fr_n:.3f}")
    print(f"[全帧]   TF: n={n0} RMSE={np.sqrt(ss0/n0):.3f} MAE={mae0/n0:.3f}")
    print(f"[全帧]   FRE: n={n0} RMSE={np.sqrt(fr0/n0):.3f} MAE={frmae0/n0:.3f}")
    print("\n--- 减速帧TF误差TOP8段 ---")
    for r in sorted(res,key=lambda x:-x['tf_ss'])[:8]:
        if r['tf_n']:
            print(f"  seg{r['seg']:>3}: n={r['tf_n']:>5} TF_RMSE={np.sqrt(r['tf_ss']/r['tf_n']):6.3f} FRE_RMSE={np.sqrt(r['fr_ss']/r['fr_n']):6.3f}")
if __name__=="__main__": main()
