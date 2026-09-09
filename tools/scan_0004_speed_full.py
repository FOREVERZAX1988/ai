#!/usr/bin/env python3
"""全量扫描 0004 所有段: 轮速(ESP_VL_Radgeschw) vs carState.vEgo 对比 + 高速段定位"""
import glob, sys, os
sys.path.insert(0,"/data/openpilot"); sys.path.insert(0,"/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader

segs=sorted(glob.glob('/data/media/0/realdata/00000004--*/rlog.zst'))
for f in segs:
    sn=os.path.basename(os.path.dirname(f)).split('--')[-1]
    vego_max=0.0; wheel_max=0.0; hi_frames=0; hi_wheel=0; n_veg=0; n_whl=0
    for m in LogReader(f):
        w=m.which()
        if w=='carState':
            v=m.carState.vEgo*3.6
            if v>vego_max: vego_max=v
            if v>60: hi_frames+=1
            n_veg+=1
        elif w=='can':
            for c in m.can:
                if c.address==0x103 and len(c.dat)>=4:
                    raw=((c.dat[3]&0x0F)<<8 | c.dat[2]) & 0x0FFF
                    v=raw*0.1
                    if v>wheel_max and v<300: wheel_max=v
                    if v>60: hi_wheel+=1
                    n_whl+=1
    if vego_max>20 or wheel_max>20:
        print(f"seg{sn:>2}: vEgoMax={vego_max:6.1f}  wheelMax={wheel_max:6.1f}  vEgo>60={hi_frames:6d}  wheel>60={hi_wheel:6d}")
