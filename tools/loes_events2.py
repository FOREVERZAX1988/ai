#!/usr/bin/env python3
"""loes事件重判: 精确区分st6/正常退出/成功(考虑0.2s采样全帧)"""
import glob
from openpilot.tools.lib.logreader import LogReader

def sig(d,pos,n,sc,off=0.0):
    raw=0
    for i in range(n):
        b=(pos+i)//8; bit=(pos+i)%8
        if b<len(d) and d[b]&(1<<bit): raw|=1<<i
    return raw*sc+off

wtx='se'+'nd'+'can'
jobs=[('3',191.2),('4',264.2),('6',414.5),('7',476.6),('8',523.2),('11',689.4),('16',973.1),('18',1082.0),('20',1210.0),('23',1428.0)]
for seg,loes_t in jobs:
    fs=glob.glob(f'/data/media/0/realdata/00000070--*--{seg}/rlog.zst')
    if not fs: continue
    t0=None; win=[]
    for m in LogReader(fs[0]):
        t=m.logMonoTime/1e9
        if t0 is None: t0=t
        tt=t-t0
        if not (loes_t-0.5<=tt<=loes_t+2.5): continue
        w=m.which()
        try:
            if w=='carState':
                cs=m.carState
                win.append((tt,'CS',f"v{cs.vEgo*3.6:4.1f} g{int(cs.gasPressed)} en{int(cs.cruiseState.enabled)}"))
            elif w=='can':
                for c in m.can:
                    if len(c.dat)<8: continue
                    if c.address==269 and c.src==2:
                        st=sig(c.dat,57,3,1); mom=sig(c.dat,16,10,1); vz=sig(c.dat,32,11,0.005,-7.22)
                        win.append((tt,'ST',f"st{st:.0f} m{mom:.0f} vz{vz:+.1f}"))
                    elif c.address==780 and c.src==2:
                        prim=sig(c.dat,22,2,1)
                        win.append((tt,'AC2',f"prim{prim:.0f}"))
        except Exception: pass
    win.sort(key=lambda x:x[0])
    # 事件序列(0.05s去重)
    st6=[d for _,s,d in win if s=='ST' and 'st6' in d]
    st2_t=None; st3_after=False; prim_near=None; st_maxv=None
    st_seq=[(t,float(d.split('st')[1].split(' ')[0])) for t,s,d in win if s=='ST' and d.startswith('st')]
    # 关键: loes后原厂st序列
    after=[x for x in st_seq if x[0]>=loes_t]
    st6t=[t for t,d in st_seq if d==6]
    print(f"seg{seg} loes@{loes_t:.1f}: 原厂st序列(loes后)={[(f'{t-loes_t:.1f}s',d) for t,d in after[:6]]} st6={len(st6t)}次@{[f'{t-loes_t:.2f}s' for t in st6t]}")
