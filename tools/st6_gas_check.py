#!/usr/bin/env python3
"""st6前是否超驰(gasPressed/gas_override)——判断mom自算是否执行"""
import glob
from openpilot.tools.lib.logreader import LogReader

def sig(d,pos,n,sc,off=0.0):
    raw=0
    for i in range(n):
        b=(pos+i)//8; bit=(pos+i)%8
        if b<len(d) and d[b]&(1<<bit): raw|=1<<i
    return raw*sc+off

jobs=[('6',414.7,'00000070'),('18',1082.2,'00000070')]
for seg,pt,prefix in jobs:
    fs=glob.glob(f'/data/media/0/realdata/{prefix}--*--{seg}/rlog.zst')
    if not fs: continue
    t0=None; rows=[]
    for m in LogReader(fs[0]):
        t=m.logMonoTime/1e9
        if t0 is None: t0=t
        tt=t-t0
        if not (pt-2.5<=tt<=pt+0.5): continue
        w=m.which()
        try:
            if w=='carState':
                cs=m.carState
                rows.append((tt,f"gas={int(cs.gasPressed)} brake={int(cs.brakePressed)} vEgo={cs.vEgo*3.6:.1f} en={int(cs.cruiseState.enabled)}"))
            elif w=='carControl':
                cc=m.carControl
                rows.append((tt,f"cc.longActive={int(cc.longActive)} en={int(cc.enabled)}"))
            elif w=='carControlSP':
                rows.append((tt,f"gasOverride={int(m.carControlSP.gasPressedOverride if hasattr(m.carControlSP,'gasPressedOverride') else 0)}"))
            elif w=='can':
                for c in m.can:
                    if c.address==269 and c.src==2 and len(c.dat)>=8:
                        rows.append((tt,f"原厂269 st{sig(c.dat,57,3,1):.0f} mom{sig(c.dat,16,10,1):.0f} vz{sig(c.dat,32,11,0.005,-7.22):+.2f}"))
        except Exception: pass
    rows.sort(key=lambda x:x[0])
    print(f"\n== {prefix} seg{seg} st6@{pt}s 前2.5s gas/超驰检查(0.2s采样) ==")
    prev=-9
    for t,s in rows:
        if t-prev<0.2: continue
        prev=t
        print(f"{t-pt:+5.2f}s {s}")
