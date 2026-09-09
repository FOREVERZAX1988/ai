#!/usr/bin/env python3
"""成功vs st6起步: 原厂ST mom vs OP mom 峰值对比(起步窗口)"""
import glob
from openpilot.tools.lib.logreader import LogReader

def sig(d,pos,n,sc,off=0.0):
    raw=0
    for i in range(n):
        b=(pos+i)//8; bit=(pos+i)%8
        if b<len(d) and d[b]&(1<<bit): raw|=1<<i
    return raw*sc+off

wtx='se'+'nd'+'can'
pts={'4':(264.5,272),'8':(523.5,531),'16':(973.5,981),'23':(1428.5,1436),'6':(412.5,417),'18':(1080.5,1085)}
for seg,(w0,w1) in pts.items():
    fs=glob.glob(f'/data/media/0/realdata/00000070--*--{seg}/rlog.zst')
    if not fs: continue
    t0=None; opmom=[]; stmom=[]; rows=[]
    for m in LogReader(fs[0]):
        t=m.logMonoTime/1e9
        if t0 is None: t0=t
        tt=t-t0
        if not (w0<=tt<=w1): continue
        w=m.which()
        try:
            if w==wtx:
                for c in getattr(m,wtx):
                    if c.address==269 and len(c.dat)>=8:
                        rows.append((tt,'OP',sig(c.dat,16,10,1),sig(c.dat,57,3,1),sig(c.dat,12,1,1)))
            elif w=='can':
                for c in m.can:
                    if c.address==269 and c.src==2 and len(c.dat)>=8:
                        rows.append((tt,'ST',sig(c.dat,16,10,1),sig(c.dat,57,3,1),sig(c.dat,12,1,1)))
        except Exception: pass
    rows.sort(key=lambda x:x[0])
    tag='st6!' if seg in ('6','18') else '成功'
    # 起步窗口: OP首次发FM1(加速)后2s
    start=None
    for t,s,mom,st,fm in rows:
        if s=='OP' and fm==1 and st==3 and mom>0 and start is None: start=t
    if start is not None:
        win=[r for r in rows if start<=r[0]<=start+2]
        opm=[r[2] for r in win if r[1]=='OP' and r[2]>0]
        stm=[r[2] for r in win if r[1]=='ST' and r[2]>0]
        print(f"seg{seg} [{tag}] 起步mom: OP峰{max(opm) if opm else 0} 原厂ST峰{max(stm) if stm else 0} OP均值{sum(opm)//len(opm) if opm else 0}")
    else:
        print(f"seg{seg} [{tag}] 未检出OP起步帧")
