#!/usr/bin/env python3
"""vCruise高值(153/195)时刻 vs SLA限速数据对照——判断vCruise是否来自限速链"""
import glob
from openpilot.tools.lib.logreader import LogReader

def get_sla(m):
    try:
        lp=m.longitudinalPlanSP
        sl=lp.speedLimit.resolver
        return (float(sl.speedLimitValid), float(sl.speedLimitLastValid), float(sl.speedLimit)*3.6 if hasattr(sl,'speedLimit') else -1, str(sl.source)[:40])
    except Exception:
        return None

jobs=[('00000070','6',395,408,'153档'),('0000006c','10',601,620,'195/144档')]
for prefix,seg,w0,w1,tag in jobs:
    fs=glob.glob(f'/data/media/0/realdata/{prefix}--*--{seg}/rlog.zst')
    if not fs: continue
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
                rows.append((tt,'CS',f"vCruise={cs.vCruise*3.6:.0f} vEgo={cs.vEgo*3.6:.0f} en={int(cs.cruiseState.enabled)}"))
            elif w=='longitudinalPlanSP':
                sla=get_sla(m)
                if sla:
                    rows.append((tt,'SLA',f"valid={int(sla[0])} last={int(sla[1])} limit={sla[2]:.0f}kmh src={sla[3]}"))
        except Exception: pass
    rows.sort(key=lambda x:x[0])
    print(f"\n== {prefix} seg{seg} [{tag}] ==")
    prev=-9
    for t,s,d in rows:
        if t-prev<2.0: continue
        prev=t
        print(f"{t-w0:5.1f}s {s}: {d}")
