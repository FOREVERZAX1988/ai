#!/usr/bin/env python3
"""006f DTC事件分析: 找原厂269的st跳变(6/7)时刻 + engage点 + 故障前后帧对比"""
import glob
from openpilot.tools.lib.logreader import LogReader

def sig(d,pos,n,sc,off=0.0):
    raw=0
    for i in range(n):
        b=(pos+i)//8; bit=(pos+i)%8
        if b<len(d) and d[b]&(1<<bit): raw|=1<<i
    return raw*sc+off

wtx='se'+'nd'+'can'
for prefix in ('0000006f','0000006e'):
    fs=sorted(glob.glob(f'/data/media/0/realdata/{prefix}--*/rlog.zst'), key=lambda f:int(f.split('--')[-1].split('/')[0]))
    if not fs: continue
    print(f"===== {prefix}: {len(fs)}段 =====")
    t0=None
    for f in fs:
        seg=f.split('--')[-1].split('/')[0]
        st_ev=[]; eng_ev=[]; en_prev=False; st_prev=None; rows=[]
        for m in LogReader(f):
            t=m.logMonoTime/1e9
            if t0 is None: t0=t
            tt=t-t0
            w=m.which()
            try:
                if w=='carControl':
                    en=bool(m.carControl.enabled)
                    if en and not en_prev:
                        eng_ev.append((tt,'ENGAGE'))
                    en_prev=en
                elif w=='can':
                    for c in m.can:
                        if c.address==269 and c.src==2 and len(c.dat)>=8:
                            st=sig(c.dat,57,3,1)
                            if st_prev is not None and st!=st_prev and st in (3,4,6,7):
                                st_ev.append((tt,st_prev,st))
                            st_prev=st
            except Exception: pass
        print(f"  seg{seg}: engage点={[f'{t:.1f}s' for t,_ in eng_ev]} st跳变={[(f'{t:.1f}s',f'{a}->{b}') for t,a,b in st_ev if b in (6,7)]}")
        for t,a,b in st_ev:
            if b in (6,7):
                print(f"    !!! st {a}->{b} @段内{t:.1f}s")
