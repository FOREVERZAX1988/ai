#!/usr/bin/env python3
"""eval_fit_vs_stock.py — 拟合公式 vs 原厂数据全route误差评估(多进程并行)
流程: 用 --fit 段(0004)训练 verz/mom/axG 公式 → 在 --eval 段(0002全route)逐帧对比原厂bus2实际值
用法: python3 eval_fit_vs_stock.py --fit 00000004:12 00000004:26 --eval 00000002
输出: 全route汇总 + 分场景桶 + TOP差段
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
                    mom=gs(d,*S['ACC_Momentenanforderung'])
                    vz=gs(d,*S['ACC_Verz_anf'])
                    axg=gs(d,*S['ACC_ax_Getriebe'])
                    st=int(gs(d,*S['ACC_Status_ACC']))
                    if st==3:
                        rows.append([cs.get('v',0),cs.get('a',0),
                                     rt[0] if rt else 0, rt[1] if rt else 0,
                                     vz,mom,axg])
    return np.array(rows) if rows else None
def fit_formulas(FT):
    v,a,d,vr,vz,mom,axg=FT.T
    dec=FT[vz<0]
    Xv=np.column_stack([np.ones(len(dec)),dec[:,1],dec[:,3],dec[:,2],dec[:,0]])
    wv=np.linalg.lstsq(Xv,dec[:,4],rcond=None)[0]
    T2=FT[vz>=-0.02]
    if len(T2)>50:
        cr=np.abs(T2[:,1])<0.05
        if cr.sum()>20:
            b0,b1=np.polyfit(T2[cr,0],T2[cr,5],1)
        else: b0,b1=27.0,6.5
        resid=T2[:,5]-(b0*T2[:,0]+b1)
        acc=T2[:,1]>0.05
        k=np.polyfit(T2[acc,1],resid[acc],1)[0] if acc.sum()>10 else 55.0
    else: b0,b1,k=27.0,6.5,55.0
    accm=FT[FT[:,5]>30]
    km=np.linalg.lstsq(accm[:,5].reshape(-1,1),accm[:,6],rcond=None)[0][0] if len(accm)>10 else 0.012
    decm=FT[FT[:,4]<0]
    kv=np.linalg.lstsq(decm[:,4].reshape(-1,1),decm[:,6],rcond=None)[0][0] if len(decm)>10 else 0.0
    return wv,(b0,b1,k),(km,kv)
def eval_seg(arg):
    route,seg,formulas=arg
    t=load(route,seg)
    if t is None or len(t)==0: return None
    wv,(b0,b1,k),(km,kv)=formulas
    vz=t[:,4]; mom=t[:,5]
    r=dict(seg=int(seg),vz_n=0,vz_ss=0.0,vz_mae=0.0,vz_max=0.0,
           mom_n=0,mom_ss=0.0,mom_mae=0.0,mom_max=0.0,
           axg_n=0,axg_ss=0.0,axg_mae=0.0)
    dec=t[vz<0]
    if len(dec):
        Xv2=np.column_stack([np.ones(len(dec)),dec[:,1],dec[:,3],dec[:,2],dec[:,0]])
        e=dec[:,4]-Xv2@wv
        r['vz_n']=len(e); r['vz_ss']=float((e**2).sum()); r['vz_mae']=float(np.abs(e).sum()); r['vz_max']=float(np.abs(e).max())
    t2=t[vz>=-0.02]
    if len(t2):
        pred=np.where(t2[:,1]>0.05, b0*t2[:,0]+b1+k*t2[:,1], b0*t2[:,0]+b1)
        e=t2[:,5]-pred
        r['mom_n']=len(e); r['mom_ss']=float((e**2).sum()); r['mom_mae']=float(np.abs(e).sum()); r['mom_max']=float(np.abs(e).max())
    pred=np.where(t[:,4]<0, kv*t[:,4], km*t[:,5])
    e=t[:,6]-pred
    r['axg_n']=len(e); r['axg_ss']=float((e**2).sum()); r['axg_mae']=float(np.abs(e).sum())
    return r
def main():
    args=sys.argv[1:]
    fi=args.index('--fit') if '--fit' in args else -1
    ei=args.index('--eval') if '--eval' in args else -1
    fit_specs=args[fi+1:ei] if fi>=0 else []
    eval_specs=args[ei+1:] if ei>=0 else []
    def split(s): r,_,g=s.rpartition(':'); return r,int(g)
    FT=None
    for s in fit_specs:
        t=load(*split(s))
        if t is None: print(f"[{s}] 无数据"); continue
        FT=t if FT is None else np.vstack([FT,t])
    if FT is None: print("无训练数据"); sys.exit(1)
    wv,(b0,b1,k),(km,kv)=fit_formulas(FT)
    print(f"训练段: {fit_specs} n={len(FT)}")
    print(f"verz={wv[0]:+.3f}*aEgo {wv[1]:+.3f}*vRel {wv[2]:+.3f}*dRel {wv[3]:+.3f}*vEgo {wv[4]:+.2f}")
    print(f"mom_base={b0:.2f}*v {b1:+.1f} ; k={k:.1f}*aEgo ; axG: 加速{km:.4f}*mom 减速{kv:.4f}*verz", flush=True)
    route=eval_specs[0]
    segs=[os.path.basename(os.path.dirname(p)).split('--')[-1] for p in sorted(glob.glob(f"{BASE}/{route}--*--*/rlog.zst"))]
    print(f"评估 route {route}: {len(segs)} 段 (并行4)", flush=True)
    args_pool=[(route,s,(wv,(b0,b1,k),(km,kv))) for s in segs]
    with Pool(4) as pool:
        res=[r for r in pool.map(eval_seg,args_pool) if r is not None]
    vz_n=sum(r['vz_n'] for r in res); vz_ss=sum(r['vz_ss'] for r in res); vz_mae=sum(r['vz_mae'] for r in res)
    mom_n=sum(r['mom_n'] for r in res); mom_ss=sum(r['mom_ss'] for r in res); mom_mae=sum(r['mom_mae'] for r in res)
    axg_n=sum(r['axg_n'] for r in res); axg_ss=sum(r['axg_ss'] for r in res); axg_mae=sum(r['axg_mae'] for r in res)
    print(f"\n===== {route} 全route (有效段 {len(res)}) 拟合公式 vs 原厂 =====")
    if vz_n: print(f"[verz] 减速帧 n={vz_n:>6} RMSE={np.sqrt(vz_ss/vz_n):7.3f} MAE={vz_mae/vz_n:7.3f} max={max(r['vz_max'] for r in res):7.3f}")
    if mom_n: print(f"[mom ] 力矩生效帧 n={mom_n:>6} RMSE={np.sqrt(mom_ss/mom_n):7.2f} MAE={mom_mae/mom_n:7.2f} max={max(r['mom_max'] for r in res):7.2f}")
    if axg_n: print(f"[axG ] 全st3帧 n={axg_n:>6} RMSE={np.sqrt(axg_ss/axg_n):7.3f} MAE={axg_mae/axg_n:7.3f}")
    print("\n--- 按mom RMSE排序 TOP8差段 ---")
    for r in sorted(res,key=lambda x:-x['mom_ss'])[:8]:
        print(f"  seg{r['seg']:>3}: vz n={r['vz_n']:>5} rmse={np.sqrt(r['vz_ss']/r['vz_n']) if r['vz_n'] else 0:6.2f} | mom n={r['mom_n']:>5} rmse={np.sqrt(r['mom_ss']/r['mom_n']) if r['mom_n'] else 0:6.1f} | axG n={r['axg_n']:>5} rmse={np.sqrt(r['axg_ss']/r['axg_n']) if r['axg_n'] else 0:6.3f}")
if __name__=="__main__": main()
