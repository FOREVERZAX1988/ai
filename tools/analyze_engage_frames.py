#!/usr/bin/env python3
"""engage瞬间逐帧分析: 269帧字段对比"""
import glob
from openpilot.tools.lib.logreader import LogReader

def sig(d,pos,n,sc,off=0.0):
    raw=0
    for i in range(n):
        b=(pos+i)//8; bit=(pos+i)%8
        if b<len(d) and d[b]&(1<<bit): raw|=1<<i
    return raw*sc+off

def flds(d):
    return dict(st=sig(d,57,3,1), mom=sig(d,16,10,1), vz=sig(d,32,11,0.005,-7.22),
                fm=sig(d,12,1,1), fv=sig(d,13,1,1), loes=sig(d,43,1,1),
                axg=sig(d,48,9,0.024,-2.016), anh=sig(d,62,1,1),
                vorb=sig(d,47,1,1), esp=sig(d,61,1,1), stsp=sig(d,44,2,1))

wtx='se'+'nd'+'can'
jobs=[('0000006e','0',51.5,55.5),('0000006f','0',57.0,61.0)]
for prefix,seg,w0,w1 in jobs:
    fs=sorted(glob.glob(f'/data/media/0/realdata/{prefix}--*/rlog.zst'), key=lambda x:int(x.split('--')[-1].split('/')[0]))
    path=[p for p in fs if p.split('--')[-1].split('/')[0]==seg][0]
    t0=None; rows=[]
    for m in LogReader(path):
        t=m.logMonoTime/1e9
        if t0 is None: t0=t
        tt=t-t0
        if not (w0<=tt<=w1): continue
        w=m.which()
        try:
            if w==wtx:
                for c in getattr(m,wtx):
                    if c.address==269 and len(c.dat)>=8:
                        rows.append((tt,'OP',flds(c.dat)))
            elif w=='can':
                for c in m.can:
                    if c.address==269 and c.src==2 and len(c.dat)>=8:
                        rows.append((tt,'ST',flds(c.dat)))
            elif w=='carControl':
                rows.append((tt,'cc',dict(en=int(m.carControl.enabled),st=-9)))
        except Exception: pass
    rows.sort(key=lambda x:x[0])
    print(f"\n===== {prefix} seg{seg} engage窗口 =====")
    prev=-1e9
    for t,src,d in rows:
        if t-prev<0.08: continue
        prev=t
        if src=='cc':
            print(f"{t:5.1f} cc.en={d['en']}")
        else:
            print(f"{t:5.1f} {src}: st={d['st']:.0f} mom={d['mom']:3.0f} vz={d['vz']:+5.2f} "
                  f"FM{d['fm']:.0f} FV{d['fv']:.0f} loes{d['loes']:.0f} axG{d['axg']:+4.2f} "
                  f"anh{d['anh']:.0f} 预充压{d['vorb']:.0f} ESP{d['esp']:.0f} SSI{d['stsp']:.0f}")
