#!/usr/bin/env python3
"""00000070全段: 原厂269 st=6瞬跳定位 + Prim_Anz/OP帧帧级时序"""
import glob
from openpilot.tools.lib.logreader import LogReader

def sig(d,pos,n,sc,off=0.0):
    raw=0
    for i in range(n):
        b=(pos+i)//8; bit=(pos+i)%8
        if b<len(d) and d[b]&(1<<bit): raw|=1<<i
    return raw*sc+off

def f269(d):
    return f"st{sig(d,57,3,1):.0f} mom{sig(d,16,10,1):.0f} vz{sig(d,32,11,0.005,-7.22):+.2f} FM{sig(d,12,1,1):.0f} FV{sig(d,13,1,1):.0f}"

def f780(d):
    return f"prim{sig(d,22,2,1):.0f} wsk{sig(d,12,10,0.32):.0f}kmh azg{sig(d,61,3,1):.0f}"

wtx='se'+'nd'+'can'
fs=sorted(glob.glob('/data/media/0/realdata/00000070--*/rlog.zst'), key=lambda f:int(f.split('--')[-1].split('/')[0]))
print(f"共{len(fs)}段")
for f in fs:
    seg=f.split('--')[-1].split('/')[0]
    t0=None; prev_st=None; st6pts=[]
    for m in LogReader(f):
        t=m.logMonoTime/1e9
        if t0 is None: t0=t
        if m.which()=='can':
            for c in m.can:
                if c.address==269 and c.src==2 and len(c.dat)>=8:
                    st=sig(c.dat,57,3,1)
                    if st==6 and prev_st is not None and prev_st!=6:
                        st6pts.append(t-t0)
                    prev_st=st
    if not st6pts:
        print(f"seg{seg}: 无st6"); continue
    print(f"seg{seg}: st6点{len(st6pts)}个: {[f'{p:.1f}s' for p in st6pts]}")
    for pt in st6pts:
        print(f" --- seg{seg} st6@{pt:.1f}s 时序(-0.6~+1.2s) ---")
        buff=[]; t0s=None
        for m in LogReader(f):
            t=m.logMonoTime/1e9
            if t0s is None: t0s=t
            tt=t-t0s
            if not (pt-0.6<=tt<=pt+1.2): continue
            w=m.which()
            try:
                if w==wtx:
                    for c in getattr(m,wtx):
                        if c.address==269: buff.append((tt,'OP269 ',f269(c.dat)))
                        elif c.address==780: buff.append((tt,'OP780 ',f780(c.dat)))
                elif w=='can':
                    for c in m.can:
                        if c.address==269 and c.src==2: buff.append((tt,'原厂269',f269(c.dat)))
                        elif c.address==780 and c.src==2: buff.append((tt,'原厂780',f780(c.dat)))
                elif w=='carState':
                    cs=m.carState.cruiseState
                    buff.append((tt,'carState',f"en={int(cs.enabled)} avail={int(cs.available)}"))
            except Exception: pass
        buff.sort(key=lambda x:x[0])
        prev=-9
        for t,s,d in buff:
            if t-prev<0.04: continue
            prev=t
            print(f"{t-pt:+6.2f}s {s}: {d}")
