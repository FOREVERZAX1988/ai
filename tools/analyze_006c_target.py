#!/usr/bin/env python3
"""601-608转盘: MPC目标速度vTarget vs 设定vCruise vs 实际v —— 判断-1.2要刹到多少"""
import glob
from openpilot.tools.lib.logreader import LogReader
fs=sorted(glob.glob('/data/media/0/realdata/0000006c--79e4b58991--*/rlog.zst'), key=lambda f:int(f.split('--')[-1].split('/')[0]))
t0=None
for m in LogReader(fs[0]):
    if m.which() in ('can','carState'):
        t0=m.logMonoTime/1e9; break
def ga(obj, *names):
    for n in names:
        try:
            v=getattr(obj,n)
            if isinstance(v,float): return v
        except Exception: pass
    return None
last={}
fields=None
for f in fs[10:14]:
    for m in LogReader(f):
        t=m.logMonoTime/1e9-t0
        if t>750 or t<590: continue
        w=m.which()
        if w=='longitudinalPlan':
            p=m.longitudinalPlan
            if fields is None:
                try: fields=[a for a in dir(p) if not a.startswith('_')]
                except Exception: pass
            last['aT']=float(p.aTarget)
            for fn in ('vTarget','vCruise'):
                v=ga(p,fn)
                if v is not None: last[fn]=float(v)
        elif w=='carState':
            last['v']=float(m.carState.vEgo)
            last['vCruise']=float(m.carState.vCruise)
            if 'lastp' not in last or t-last['lastp']>=0.2:
                last['lastp']=t
                if 590<=t<=612 or 626<=t<=634:
                    print(f"{t:6.2f} v={last.get('v',0):5.1f} aT={last.get('aT',0):6.2f} "
                          f"vTarget={last.get('vTarget',float('nan')):5.1f} vCruise(设定)={last.get('vCruise',0)*3.6:5.1f}km/h")
