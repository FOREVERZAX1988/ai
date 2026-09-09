#!/usr/bin/env python3
"""只看起步窗口: seg8保持511-516→起步516后; seg3保持186-229→起步229后"""
import glob
from openpilot.tools.lib.logreader import LogReader

def sig(d,pos,n,sc,off=0.0):
    raw=0
    for i in range(n):
        b=(pos+i)//8; bit=(pos+i)%8
        if b<len(d) and d[b]&(1<<bit): raw|=1<<i
    return raw*sc+off

def f269(d):
    return f"st{sig(d,57,3,1):.0f} mom{sig(d,16,10,1):.0f} vz{sig(d,32,11,0.005,-7.22):+.2f} FM{sig(d,12,1,1):.0f}"

wtx='se'+'nd'+'can'
jobs=[('0000006c','8',512,534),('0000006c','3',224,252)]
for prefix,seg,w0,w1 in jobs:
    fs=glob.glob(f'/data/media/0/realdata/{prefix}--*--{seg}/rlog.zst')
    if not fs: continue
    t0=None; rows=[]
    for m in LogReader(fs[0]):
        t=m.logMonoTime/1e9
        if t0 is None: t0=t
        tt=t-t0
        if not (w0<=tt<=w1): continue
        w=m.which()
        try:
            if w==wtx:
                for c in getattr(m,wtx):
                    if c.address==269: rows.append((tt,'OP',f269(c.dat)))
            elif w=='can':
                for c in m.can:
                    if c.address==269 and c.src==2: rows.append((tt,'ST',f269(c.dat)))
            elif w=='carState':
                cs=m.carState
                rows.append((tt,'cc',f"vEgo{cs.vEgo*3.6:4.1f} gas{int(cs.gasPressed)} en{int(cs.cruiseState.enabled)}"))
        except Exception: pass
    rows.sort(key=lambda x:x[0])
    print(f"\n== {prefix} seg{seg} {w0}-{w1}s 起步窗口(0.2s) ==")
    prev=-9
    for t,s,d in rows:
        if t-prev<0.2: continue
        prev=t
        print(f"{t-w0:5.1f}s {s}: {d}")
