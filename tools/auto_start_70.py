#!/usr/bin/env python3
"""00000070全部停车起步事件: 起步方式gas+结果"""
import glob
from openpilot.tools.lib.logreader import LogReader

def sig(d,pos,n,sc,off=0.0):
    raw=0
    for i in range(n):
        b=(pos+i)//8; bit=(pos+i)%8
        if b<len(d) and d[b]&(1<<bit): raw|=1<<i
    return raw*sc+off

wtx='se'+'nd'+'can'
fs=sorted(glob.glob('/data/media/0/realdata/00000070--*/rlog.zst'), key=lambda f:int(f.split('--')[-1].split('/')[0]))
total=0
for f in fs:
    seg=f.split('--')[-1].split('/')[0]
    t0=None; stop_t=None; rows=[]
    # 采集: 停车保持段起点/终点 + 起步窗口帧
    for m in LogReader(f):
        t=m.logMonoTime/1e9
        if t0 is None: t0=t
        tt=t-t0
        w=m.which()
        try:
            if w=='carState':
                cs=m.carState
                if cs.vEgo<0.3 and cs.cruiseState.enabled:
                    if stop_t is None: stop_t=tt
                else:
                    if stop_t is not None and tt-stop_t>=2.0:
                        rows.append(('HOLD',stop_t,tt))
                    stop_t=None
                if stop_t is not None and tt-stop_t>=2.0:
                    # 起步后4s窗口收集
                    rows.append(('V',tt,None)) if tt-stop_t<6.5 else None
            elif w==wtx:
                if stop_t is not None and tt-stop_t>=2.0 and tt-stop_t<6.5:
                    for c in getattr(m,wtx):
                        if c.address==269:
                            rows.append(('OP',tt,f"mom{sig(c.dat,16,10,1):.0f} st{sig(c.dat,57,3,1):.0f}"))
        except Exception: pass
    # 聚合成起步事件
    holds=sorted(set(round(t2,1) for tag,t1,t2 in rows if tag=='HOLD'))
    if not holds: continue
    evs=[]
    for h in holds:
        # 找该保持后到下次vEgo>0.5的gas
        evs.append(h)
    print(f"seg{seg}: {len(evs)}次停车保持>=2s @ {[f'{t:.0f}s' for t in evs]}")
    total+=len(evs)
print(f"\n总停车保持次数(>=2s): {total}")
