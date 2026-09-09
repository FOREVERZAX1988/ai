#!/usr/bin/env python3
"""006c(0904代码)有没有停车保持场景(vEgo<0.3m/s持续3s+)——用于判断能否对比起步st6"""
import glob
from openpilot.tools.lib.logreader import LogReader

fs=sorted(glob.glob('/data/media/0/realdata/0000006c--*/rlog.zst'), key=lambda f:int(f.split('--')[-1].split('/')[0]))
for f in fs:
    seg=f.split('--')[-1].split('/')[0]
    t0=None; stop_s=0; stop_start=None; stops=[]
    en=False
    for m in LogReader(f):
        t=m.logMonoTime/1e9
        if t0 is None: t0=t
        tt=t-t0
        w=m.which()
        try:
            if w=='carState':
                v=m.carState.vEgo
                en=m.carState.cruiseState.enabled
                if v<0.3 and en:
                    if stop_start is None: stop_start=tt
                else:
                    if stop_start is not None and tt-stop_start>3:
                        stops.append((stop_start,tt))
                    stop_start=None
        except Exception: pass
    if stops:
        print(f"seg{seg}: {len(stops)}次停车保持(>3s): {[f'{a:.0f}-{b:.0f}s' for a,b in stops][:6]}")
