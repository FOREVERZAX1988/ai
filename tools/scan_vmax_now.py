#!/usr/bin/env python3
import glob, sys, re
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader

def seg_num(p):
    m=re.search(r"--(\d+)/(?:rlog|qlog).zst$", p)
    return int(m.group(1)) if m else -1

targets={"00000004": range(18,28), "00000049": list(range(0,40))}
for pre,segs in targets.items():
    files=sorted(glob.glob(f"/data/media/0/realdata/{pre}--*/rlog.zst"), key=seg_num)
    print(f"\n=== {pre} ===")
    for r in files:
        sn=seg_num(r)
        if sn not in segs: continue
        vmax=0.0; wmax=0.0; n=0
        try:
            for msg in LogReader(r):
                if msg.which()=="carState":
                    v=msg.carState.vEgo*3.6
                    if v>vmax: vmax=v
                elif msg.which()=="can":
                    for c in msg.can:
                        if c.address==0x103 and len(c.dat)>=2:
                            w=((c.dat[1]&0x0f)<<8 | c.dat[0])*0.1
                            if w>wmax and w<300: wmax=w
                            break
                n+=1
                if n>600000: break  # cap
        except Exception as e:
            print(f"  seg{sn}: ERR {e}"); continue
        tag="  <<HIGHWAY" if vmax>70 else ""
        print(f"  seg{sn}: vEgoMax={vmax:6.1f}km/h  wheelMax={wmax:6.1f}km/h{n:8d}{tag}")
