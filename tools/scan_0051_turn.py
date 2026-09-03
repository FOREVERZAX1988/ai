#!/usr/bin/env python3
"""扫描0051全部段qlog: 找大右弯候选(转角<-80°)+候选段内最小转角时刻/车速"""
import glob
from openpilot.tools.lib.logreader import LogReader

fs=sorted(glob.glob('/data/media/0/realdata/00000051--*/qlog.zst'), key=lambda f:int(f.split('--')[-1].split('/')[0]))
print(f"0051 qlog段数={len(fs)}")
for fi,f in enumerate(fs):
    seg=f.split('--')[-1].split('/')[0]
    mn=None; mn_t=0; v_at_mn=0; t0=None
    for m in LogReader(f):
        t=m.logMonoTime/1e9
        if t0 is None: t0=t
        if m.which()=='carState':
            ang=float(m.carState.steeringAngleDeg)
            if mn is None or ang<mn:
                mn=ang; mn_t=(t-t0); v_at_mn=float(m.carState.vEgo)
    if mn is not None and mn<-70:
        print(f"seg{seg}: 最小转角={mn:+.0f}° @{mn_t:6.1f}s v={v_at_mn:4.1f}  <--候选")
    elif mn is not None:
        print(f"seg{seg}: 最小转角={mn:+.0f}° @{mn_t:6.1f}s")
