#!/usr/bin/env python3
import glob
from openpilot.tools.lib.logreader import LogReader
fs=sorted(glob.glob('/data/media/0/realdata/0000006c--79e4b58991--*/rlog.zst'), key=lambda f:int(f.split('--')[-1].split('/')[0]))
t0=None
for m in LogReader(fs[0]):
    if m.which() in ('can','carState'):
        t0=m.logMonoTime/1e9; break
last={'at':0,'ca':0,'v':0,'lp':0,'ld':0}
for f in fs[10:14]:
    for m in LogReader(f):
        t=m.logMonoTime/1e9-t0
        if t>750 or t<596: continue
        w=m.which()
        if w=='longitudinalPlan': last['at']=float(m.longitudinalPlan.aTarget)
        elif w=='carControl':
            try: last['ca']=float(m.carControl.actuators.accel)
            except Exception: pass
        elif w=='radarState':
            ld=m.radarState.leadOne
            last['ld']=float(ld.dRel) if ld.present else 0; last['lp']=int(ld.present)
        elif w=='carState':
            last['v']=float(m.carState.vEgo)
            if 'lastp' not in last or t-last['lastp']>=0.25:
                last['lastp']=t
                # 事件窗内打印(细分到0.25s看翻转)
                if (599<=t<=608) or (628<=t<=638) or (664<=t<=678) or (702<=t<=720) or (736<=t<=746):
                    print(f"{t:6.2f} v={last['v']:5.1f} aT={last['at']:6.2f} CCaccel={last['ca']:6.2f} ld={'Y' if last['lp'] else 'N'}{last['ld']:4.0f}")
