#!/usr/bin/env python3
"""解码 bus2 原厂 ACC 帧(0x30C=780 Abstandsindex / 0x324=804 前车速度) 并与 radarState 对照。"""
import sys
import numpy as np
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader  # noqa: E402

seg = sys.argv[1]
t0, t1 = (float(sys.argv[2]), float(sys.argv[3])) if len(sys.argv) > 3 else (0.0, 1e9)
rp = f"/data/media/0/realdata/{seg}/rlog.zst"

addrs = {}
nk = 0
rows = []
for m in LogReader(rp):
    t = m.logMonoTime / 1e9
    w = m.which()
    if w == "can":
        for c in m.can:
            if t < t0 or t > t1:
                continue
            if c.src == 2 and c.address in (780, 804, 1021):
                d = c.dat
                if c.address == 780:
                    idx = (d[3] | (d[4] << 8)) & 0x3FF
                    rows.append((t, "ACC_02", f"idx={idx}"))
                    addrs[780] = idx
                elif c.address == 804:
                    v = ((d[5] | (d[6] << 8)) & 0x3FF) * 0.32
                    rows.append((t, "ACC_04", f"leadspd={v:.1f}km/h"))
    elif w == "radarTracks":
        pts = m.radarTracks.points
        nk += 1 if len(pts) == 0 else 0
    elif w == "radarState" and t0 <= t <= t1:
        lo = m.radarState.leadOne
        rows.append((t, "radarState", f"pres={int(lo.present)} dRel={float(lo.dRel):.2f} "
                                      f"vRel={float(lo.vRel):.2f} radar={int(lo.radar)} mprob={float(lo.modelProb):.2f}"))
rows.sort()
for t, k, s in rows:
    print(f"{t:.3f} {k:10s} {s}")
print(f"\n[radarTracks empty msgs: {nk} in window]")
