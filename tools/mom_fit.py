#!/usr/bin/env python3
"""mom_fit.py — 原厂ACC力矩(mom)黑盒拟合 + 误差评估
模型: mom = base(vEgo) + k*aEgo(aEgo>0), 减速mom=0
用法: python3 mom_fit.py --train ROUTE:SEG ... --val ROUTE:SEG ...
输出: 拟合系数/训练验证RMSE/分车速桶误差/与当前代码曲线对比
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
        elif w=='can':
            for c in m.can:
                if c.address==269 and c.src==2 and len(c.dat)>=8:
                    d=bytes(c.dat)
                    mom=gs(d,*S['ACC_Momentenanforderung']); st=int(gs(d,*S['ACC_Status_ACC']))
                    vz=gs(d,*S['ACC_Verz_anf'])
                    if st==3:
                        rows.append([cs.get('v',0), cs.get('a',0), mom, vz])
    return np.array(rows) if rows else None
def main():
    args=sys.argv[1:]
    if '--train' in args: args.remove('--train')
    vi=args.index('--val') if '--val' in args else len(args)
    tr_specs=args[:vi] if vi else []
    val_specs=args[vi+1:] if vi<len(args) else []
    def split(s): r,_,g=s.rpartition(':'); return r,int(g)
    # 训练数据合并
    T=None
    for s in tr_specs:
        t=load(*split(s))
        if t is None: continue
        T=t if T is None else np.vstack([T,t])
    if T is None: print("无训练数据"); sys.exit(1)
    # 只保留力矩生效帧（verz>=0：非减速；减速时原厂 mom=0 由 verz 负责，混入会拉低基线）
    T=T[T[:,3]>=-0.02]
    if len(T)<100: print(f"力矩生效帧不足({len(T)})，段可能全是减速"); sys.exit(1)
    v,a,m=T[:,0],T[:,1],T[:,2]
    # 巡航基线: 取 |a|<0.05 帧拟合 mom=base(v)
    cr=(np.abs(a)<0.05)
    if cr.sum()>50:
        b0,b1=np.polyfit(v[cr],m[cr],1)
        base=np.polyval([b0,b1],v)
        resid=m-base
        # 加速增量: a>0 时 resid≈k*a
        acc=a>0.05
        if acc.sum()>20:
            k=np.polyfit(a[acc],resid[acc],1)[0]
        else:
            k=0.0
    else:
        b0,b1,k=27.0,6.5,55.0
    print(f"拟合: mom_base(v)= {b0:.2f}*v + {b1:.2f} ; 加速增量 k= {k:.2f}*aEgo")
    # 预测函数
    def pred(vv,aa):
        b=b0*vv+b1
        return np.where(aa>0.05, b+k*aa, b)
    # 训练误差
    yh=pred(v,a)
    e=m-yh
    print(f"--- 训练(合并) n={len(m)} RMSE={np.sqrt((e**2).mean()):.1f} MAE={np.abs(e).mean():.1f} max={np.abs(e).max():.1f}")
    # 分车速桶
    for lo,hi,lab in [(0,5,"0-5m/s"),(5,10,"5-10"),(10,15,"10-15"),(15,20,"15-20"),(20,30,"20-30")]:
        mm=(v>=lo)&(v<hi)
        if mm.sum()>10:
            print(f"   v{lab}: n={mm.sum()} MAE={np.abs(e[mm]).mean():.1f} max={np.abs(e[mm]).max():.1f}")
    # 验证
    for s in val_specs:
        t=load(*split(s))
        if t is None: continue
        vv,aa,mm_=t[:,0],t[:,1],t[:,2]
        y=pred(vv,aa); ee=mm_-y
        print(f"--- 验证 {s} n={len(mm_)} RMSE={np.sqrt((ee**2).mean()):.1f} MAE={np.abs(ee).mean():.1f} max={np.abs(ee).max():.1f}")
    # 与当前代码曲线对比(原厂巡航实测 vs 6.3v+15)
    print("\n--- 巡航基线: 当前代码(6.3v+15+低速ramp) vs 拟合 vs 原厂分桶实测 ---")
    for sp in [0,5,10,15,20,25,30]:
        mm=(v>=sp-0.5)&(v<sp+0.5)&(np.abs(a)<0.05)
        if mm.sum()>5:
            cur=27.0+(6.3*sp+15.0-27.0)*min(1.0,sp/5.56)
            print(f"  v={sp}m/s: 原厂实测≈{m[mm].mean():.0f} 拟合={b0*sp+b1:.0f} 当前代码={cur:.0f} (原厂-当前={m[mm].mean()-cur:+.0f})")
if __name__=='__main__': main()
