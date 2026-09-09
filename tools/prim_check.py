#!/usr/bin/env python3
"""全部loes窗口的prim_anz(ACC_02原厂)值——验证"prim=1放行/prim=0拦截"判据"""
import glob
from openpilot.tools.lib.logreader import LogReader

def sig(d,pos,n,sc,off=0.0):
    raw=0
    for i in range(n):
        b=(pos+i)//8; bit=(pos+i)%8
        if b<len(d) and d[b]&(1<<bit): raw|=1<<i
    return raw*sc+off

jobs=[('3',191.2,'成功'),('4',264.2,'成功'),('6',414.5,'st6'),('7',476.6,'成功'),
      ('8',523.2,'成功'),('11',689.4,'未起步'),('16',973.1,'成功'),('18',1082.0,'st6'),
      ('20',1210.0,'未起步'),('23',1428.0,'成功')]
for seg,loes_t,tag in jobs:
    fs=glob.glob(f'/data/media/0/realdata/00000070--*--{seg}/rlog.zst')
    if not fs: continue
    t0=None; prims=[]; robjs=[]
    for m in LogReader(fs[0]):
        t=m.logMonoTime/1e9
        if t0 is None: t0=t
        tt=t-t0
        if not (loes_t-1.5<=tt<=loes_t+0.5): continue
        w=m.which()
        try:
            if w=='can':
                for c in m.can:
                    if c.address==780 and c.src==2 and len(c.dat)>=8:
                        prims.append((tt,sig(c.dat,22,2,1)))
                        robjs.append((tt,sig(c.dat,46,2,1)))
        except Exception: pass
    if prims:
        pvals={p for _,p in prims}
        rvals={r for _,r in robjs}
        # loes时刻最近的prim值
        near=min(prims,key=lambda x:abs(x[0]-loes_t))[1] if prims else -1
        print(f"seg{seg} [{tag}] loes@前1.5s内prim值集合={sorted(pvals)} 最近={near} robj集合={sorted(rvals)}")
    else:
        print(f"seg{seg} [{tag}] 无ACC_02数据")
