#!/usr/bin/env python3
"""006c短保持(seg8 511-516)与长保持(seg3 229后)的起步方式对比: gas/帧mom"""
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

wtx='se'+'nd'+'can'
jobs=[('0000006c','8',505,530,'短保持5s后起步'),('0000006c','3',222,248,'长保持43s后起步')]
for prefix,seg,w0,w1,tag in jobs:
    fs=glob.glob(f'/data/media/0/realdata/{prefix}--*--{seg}/rlog.zst')
    if not fs: print(f"seg{seg}无"); continue
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
                    if c.address==269: rows.append((tt,'OP ',f269(c.dat)))
            elif w=='can':
                for c in m.can:
                    if c.address==269 and c.src==2: rows.append((tt,'原厂',f269(c.dat)))
            elif w=='carState':
                cs=m.carState
                rows.append((tt,'cc ',f"vEgo{cs.vEgo*3.6:4.1f} gas{int(cs.gasPressed)} brake{int(cs.brakePressed)} en{int(cs.cruiseState.enabled)}"))
        except Exception: pass
    rows.sort(key=lambda x:x[0])
    print(f"\n== {prefix} seg{seg} {w0}-{w1}s [{tag}] (0.15s采样) ==")
    prev=-9
    for t,s,d in rows:
        if t-prev<0.15: continue
        prev=t
        print(f"{t-w0:5.1f}s {s}: {d}")
