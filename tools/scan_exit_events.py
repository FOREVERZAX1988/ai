#!/usr/bin/env python3
"""退出点±3s的onroadEvents正式事件+steeringPressed(手打方向判定)"""
import glob
from openpilot.tools.lib.logreader import LogReader

# (seg, 退出t) — 从scan_exits来的关键点
pts=[('6',415.8,'低速ChangingLanes'),('18',1083.3,'低速无事件'),
     ('7',453.2,'中速无事件'),('14',842.4,'中速无事件'),
     ('20',1244.7,'中速无事件'),('25',1502.8,'中速无事件'),
     ('26',1569.2,'中速无事件'),('1',108.1,'TurningRight事件')]
for seg,texit,tag in pts:
    fs=glob.glob(f'/data/media/0/realdata/00000070--*--{seg}/rlog.zst')
    if not fs: continue
    f=fs[0]
    t0=None; evs=[]; sp_log=[]
    for m in LogReader(f):
        t=m.logMonoTime/1e9
        if t0 is None: t0=t
        tt=t-t0
        if not (texit-4<=tt<=texit+3): continue
        w=m.which()
        try:
            if w=='onroadEvents':
                names=[str(e.name) for e in m.onroadEvents]
                if names:
                    evs.append((tt,names))
            elif w=='carState':
                sp_log.append((tt,int(m.carState.steeringPressed)))
        except Exception: pass
    # 事件列表
    merged=[]
    for tt,names in evs:
        s=','.join(names)
        if merged and abs(merged[-1][0]-tt)<0.3 and merged[-1][1]==s: continue
        merged.append((tt,s))
    print(f"\n== seg{seg} @{texit:.1f}s [{tag}] ==")
    for tt,s in merged:
        print(f"  {tt-texit:+5.1f}s events: {s[:120]}")
    # 握盘统计: 退出前2s内有无steeringPressed=1
    pre_sp=sum(1 for tt,v in sp_log if tt<texit and v==1)
    print(f"  退出前2s内握盘(sp=1)采样: {pre_sp}")
