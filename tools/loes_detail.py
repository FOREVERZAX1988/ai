#!/usr/bin/env python3
"""loes窗口细看: 失败(seg6/18) vs 成功(seg4) — ACC_05/02/04 st信号时序对比"""
import glob
from openpilot.tools.lib.logreader import LogReader

def sig(d,pos,n,sc,off=0.0):
    raw=0
    for i in range(n):
        b=(pos+i)//8; bit=(pos+i)%8
        if b<len(d) and d[b]&(1<<bit): raw|=1<<i
    return raw*sc+off

wtx='se'+'nd'+'can'
jobs=[('6',414.5,'失败st6'),('18',1082.0,'失败st6'),('4',264.2,'成功对照')]
for seg,loes_t,tag in jobs:
    fs=glob.glob(f'/data/media/0/realdata/00000070--*--{seg}/rlog.zst')
    if not fs: continue
    t0=None; rows=[]
    for m in LogReader(fs[0]):
        t=m.logMonoTime/1e9
        if t0 is None: t0=t
        tt=t-t0
        if not (loes_t-2.5<=tt<=loes_t+4): continue
        w=m.which()
        try:
            if w=='carState':
                cs=m.carState
                rows.append((tt,'CS',f"v={cs.vEgo*3.6:4.1f} g{int(cs.gasPressed)} en{int(cs.cruiseState.enabled)}"))
            elif w==wtx:
                for c in getattr(m,wtx):
                    if c.address==269 and len(c.dat)>=8:
                        st=sig(c.dat,57,3,1); loes=sig(c.dat,43,1,1); mom=sig(c.dat,16,10,1)
                        vz=sig(c.dat,32,11,0.005,-7.22); fv=sig(c.dat,13,1,1)
                        rows.append((tt,'OP5',f"st{st:.0f} lo{loes:.0f} m{mom:.0f} vz{vz:+.1f} fv{fv:.0f}"))
            elif w=='can':
                for c in m.can:
                    if len(c.dat)<8: continue
                    if c.address==269 and c.src==2:
                        st=sig(c.dat,57,3,1); loes=sig(c.dat,43,1,1); mom=sig(c.dat,16,10,1)
                        vz=sig(c.dat,32,11,0.005,-7.22); fv=sig(c.dat,13,1,1)
                        rows.append((tt,'ST5',f"st{st:.0f} lo{loes:.0f} m{mom:.0f} vz{vz:+.1f} fv{fv:.0f}"))
                    elif c.address==780 and c.src==2:
                        anzg=sig(c.dat,61,3,1); prim=sig(c.dat,22,2,1); robj=sig(c.dat,46,2,1)
                        rows.append((tt,'AC2',f"anzg{anzg:.0f} prim{prim:.0f} robj{robj:.0f}"))
                    elif c.address==804 and c.src==2:
                        zus=sig(c.dat,22,5,1); tx=sig(c.dat,27,5,1)
                        rows.append((tt,'AC4',f"zus{zus:.0f} tx{tx:.0f}"))
        except Exception: pass
    rows.sort(key=lambda x:x[0])
    print(f"\n===== seg{seg} loes@{loes_t:.1f}s [{tag}] 窗口(-2.5~+4s) =====")
    prev=-9
    for t,s,d in rows:
        if t-prev<0.08: continue
        prev=t
        mark=' <<<loes' if abs(t-loes_t)<0.08 else (' <<<st6' if s=='ST5' and 'st6' in d else '')
        print(f"{t-loes_t:+6.2f}s {s}: {d}{mark}")
