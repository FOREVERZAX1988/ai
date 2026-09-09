#!/usr/bin/env python3
"""巡航速度三方对比: carState.vCruise(OP) / vCruiseCluster(仪表回读?) / ACC_02.wsk(原厂)"""
import glob
from openpilot.tools.lib.logreader import LogReader

def sig(d,pos,n,sc,off=0.0):
    raw=0
    for i in range(n):
        b=(pos+i)//8; bit=(pos+i)%8
        if b<len(d) and d[b]&(1<<bit): raw|=1<<i
    return raw*sc+off

# 取多个巡航采样段: seg6停车前(395-410行驶段) seg7巡航段(438-452) seg25巡航段
for seg,w0,w1 in (('6',395,408),('7',438,450)):
    fs=glob.glob(f'/data/media/0/realdata/00000070--*--{seg}/rlog.zst')
    if not fs: print(f"seg{seg}无"); continue
    t0=None; rows=[]
    for m in LogReader(fs[0]):
        t=m.logMonoTime/1e9
        if t0 is None: t0=t
        tt=t-t0
        if not (w0<=tt<=w1): continue
        w=m.which()
        try:
            if w=='carState':
                cs=m.carState
                rows.append((tt,'vCruise',cs.vCruise*3.6 if cs.vCruise else 0, cs.vCruiseCluster*3.6 if cs.vCruiseCluster else -1, float(cs.cruiseState.enabled)))
            elif w=='can':
                for c in m.can:
                    if c.address==780 and c.src==2 and len(c.dat)>=8:
                        rows.append((tt,'ACC02',sig(c.dat,12,10,0.32), -1, -1))
        except Exception: pass
    rows.sort(key=lambda x:x[0])
    print(f"\n== seg{seg} {w0}-{w1}s 巡航速度对比(1s采样) ==")
    prev=-9
    for t,s,a,b,c in rows:
        if t-prev<1.0: continue
        prev=t
        if s=='vCruise':
            print(f"{t-w0:5.1f}s OP vCruise={a:.0f}kmh 集群={b:.0f}kmh en={int(c)}")
        else:
            print(f"{t-w0:5.1f}s 原厂ACC02.wsk={a:.0f}kmh")
