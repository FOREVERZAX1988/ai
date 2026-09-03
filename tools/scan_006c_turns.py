#!/usr/bin/env python3
"""扫006c全部段qlog: 找大右弯候选(转角min<-85°) 每个弯的(段,seg内时刻,route时刻,v)"""
import glob
from openpilot.tools.lib.logreader import LogReader

fs=sorted(glob.glob('/data/media/0/realdata/0000006c--79e4b58991--*/qlog.zst'), key=lambda f:int(f.split('--')[-1].split('/')[0]))
print(f"006c qlog段数={len(fs)}")
# 每段60s左右 → route累计时间
cum=0.0
for fi,f in enumerate(fs):
    seg=f.split('--')[-1].split('/')[0]
    mn=None; mn_t=0; v_at=0; t0=None; t1=None; ang_prev=None; dur_turn=0
    for m in LogReader(f):
        t=m.logMonoTime/1e9
        if t0 is None: t0=t
        t1=t
        if m.which()=='carState':
            ang=float(m.carState.steeringAngleDeg)
            if mn is None or ang<mn:
                mn=ang; mn_t=t-t0; v_at=float(m.carState.vEgo)
    # qlog carState约20Hz? 段内时长
    segdur=(t1-t0) if t1 else 60
    if mn is not None and mn<-85:
        print(f"seg{seg}: route_t={cum+mn_t:7.1f}s seg内@{mn_t:5.1f}s 最小转角={mn:+.0f}° v={v_at:4.1f} <==大右弯")
    cum+=segdur
print(f"route累计时长≈{cum:.0f}s")
