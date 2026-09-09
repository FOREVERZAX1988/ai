#!/usr/bin/env python3
"""seg7 468-495s 起步全程: 找原厂st3->2时刻/mom/gas/事件 vs seg6/18 st6例"""
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
    return f"prim{sig(d,22,2,1):.0f} wsk{sig(d,12,10,0.32):.0f}kmh"

wtx='se'+'nd'+'can'
fs=glob.glob('/data/media/0/realdata/00000070--*--7/rlog.zst')
t0=None; rows=[]
for m in LogReader(fs[0]):
    t=m.logMonoTime/1e9
    if t0 is None: t0=t
    tt=t-t0
    if not (466<=tt<=496): continue
    w=m.which()
    try:
        if w==wtx:
            for c in getattr(m,wtx):
                if c.address==269 and len(c.dat)>=8: rows.append((tt,'OP ',f269(c.dat)))
                elif c.address==780: rows.append((tt,'OP780',f780(c.dat)))
        elif w=='can':
            for c in m.can:
                if c.address==269 and c.src==2: rows.append((tt,'原厂',f269(c.dat)))
                elif c.address==780 and c.src==2: rows.append((tt,'ST780',f780(c.dat)))
        elif w=='carState':
            cs=m.carState
            rows.append((tt,'cc ',f"vEgo{cs.vEgo*3.6:4.1f} gas{int(cs.gasPressed)} brk{int(cs.brakePressed)} en{int(cs.cruiseState.enabled)} av{int(cs.cruiseState.available)}"))
        elif w=='onroadEvents':
            names=[str(e.name) for e in m.onroadEvents]
            if names: rows.append((tt,'EV ',','.join(names)[:80]))
        elif w=='carControl':
            rows.append((tt,'CC ',f"en{int(m.carControl.enabled)} lon{int(m.carControl.longActive)} lat{int(m.carControl.latActive)}"))
    except Exception: pass
rows.sort(key=lambda x:x[0])
print(f"== 00000070 seg7 466-496s 起步+退出全程(0.15s) ==")
prev=-9
for t,s,d in rows:
    if t-prev<0.15: continue
    prev=t
    print(f"{t-475:+6.1f}s {s}: {d}")
