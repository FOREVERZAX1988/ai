#!/usr/bin/env python3
import glob, sys, re
sys.path.insert(0,"/data/openpilot"); sys.path.insert(0,"/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader
def seg_num(p):
    m=re.search(r"--(\d+)/rlog.zst$",p); return int(m.group(1)) if m else -1
# ESP_VL_Radgeschw ID 0x103, 16|12@1+ scale0.1 km/h -> bytes2..3, 12 bits LE
for sn in [19,20,21,22,26]:
    r=f"/data/media/0/realdata/00000004--915ebf086f--{sn}/rlog.zst"
    vmax=wmax=vlast=0.0; samples=0
    for msg in LogReader(r):
        if msg.which()=="carState":
            vlast=msg.carState.vEgo*3.6
            if vlast>vmax: vmax=vlast
        elif msg.which()=="can":
            for c in msg.can:
                if c.address==0x103 and len(c.dat)>=4:
                    raw=((c.dat[3]&0x0F)<<8 | c.dat[2]) & 0x0FFF
                    w=raw*0.1
                    if w>wmax and w<300:
                        wmax=w; w_at=vlast
                    samples+=1
    print(f"seg{sn}: vEgoMax={vmax:6.1f}  ESP_VL_RadgeschwMax={wmax:6.1f}  (at vEgo~{w_at:.0f})  samples={samples}")
