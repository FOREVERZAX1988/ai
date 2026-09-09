#!/usr/bin/env python3
"""退出点精读(降频版): seg18(1083.3s) + seg6(415.8s)"""
import glob
from openpilot.tools.lib.logreader import LogReader

def sig(d,pos,n,sc,off=0.0):
    raw=0
    for i in range(n):
        b=(pos+i)//8; bit=(pos+i)%8
        if b<len(d) and d[b]&(1<<bit): raw|=1<<i
    return raw*sc+off

wtx='se'+'nd'+'can'
jobs=[('00000070','18',1079.5,1085.0),('00000070','6',413.0,417.5)]
for prefix,seg,w0,w1 in jobs:
    f=glob.glob(f'/data/media/0/realdata/{prefix}--*--{seg}/rlog.zst')[0]
    t0=None; rows=[]
    for m in LogReader(f):
        t=m.logMonoTime/1e9
        if t0 is None: t0=t
        tt=t-t0
        if not (w0<=tt<=w1): continue
        w=m.which()
        try:
            if w=='carState':
                cs=m.carState
                rows.append((tt,'ST',f'vEgo={cs.vEgo*3.6:4.1f} gas={int(cs.gasPressed)} brk={int(cs.brakePressed)} dir={int(cs.leftBlinker)}{int(cs.rightBlinker)}'))
            elif w=='carControl':
                cc=m.carControl
                rows.append((tt,'cc',f'en={int(cc.enabled)} lon={int(cc.longActive)} lat={int(cc.latActive)}'))
            elif w=='selfdriveState':
                sd=m.selfdriveState
                rows.append((tt,'sd',f'alert="{str(sd.alertText1)[:36]}" st={int(sd.state)} en={int(sd.enabled)}'))
            elif w==wtx:
                for c in getattr(m,wtx):
                    if c.address==269 and len(c.dat)>=8:
                        rows.append((tt,'OP',f'st={sig(c.dat,57,3,1):.0f} mom={sig(c.dat,16,10,1):3.0f} '
                                    f'vz={sig(c.dat,32,11,0.005,-7.22):+5.2f} FM{int(sig(c.dat,12,1,1))} FV{int(sig(c.dat,13,1,1))} '
                                    f'loes{int(sig(c.dat,43,1,1))} anh{int(sig(c.dat,62,1,1))} axg={sig(c.dat,48,9,0.024,-2.016):+4.2f}'))
            elif w=='can':
                for c in m.can:
                    if c.address==269 and c.src==2 and len(c.dat)>=8:
                        rows.append((tt,'原厂',f'st={sig(c.dat,57,3,1):.0f} mom={sig(c.dat,16,10,1):3.0f} '
                                    f'vz={sig(c.dat,32,11,0.005,-7.22):+5.2f} FM{int(sig(c.dat,12,1,1))} FV{int(sig(c.dat,13,1,1))}'))
        except Exception: pass
    rows.sort(key=lambda x:x[0])
    print(f"\n===== {prefix} seg{seg} {w0}-{w1}s =====")
    prev=-1e9
    for t,src,d in rows:
        if t-prev<0.2: continue
        prev=t
        print(f"{t:6.1f} {src}: {d}")
