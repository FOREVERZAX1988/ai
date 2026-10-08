#!/usr/bin/env python3
"""原始消息 dump：seg + 时间窗，逐帧打印 vision / radarState / radarTracks / vEgo。"""
import sys
import numpy as np
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader  # noqa: E402

BASE = "/data/media/0/realdata"
seg = sys.argv[1]
t0, t1 = float(sys.argv[2]), float(sys.argv[3])
rp = f"{BASE}/{seg}/rlog.zst"
qp = f"{BASE}/{seg}/qlog.zst"

vmap = {}
for m in LogReader(qp):
    if m.which() == "carState":
        vmap[round(m.logMonoTime / 1e9, 3)] = m.carState.vEgo
vt = np.array(sorted(vmap)) if vmap else np.array([])
vv = np.array([vmap[k] for k in vt]) if vmap else np.array([])

last_en = 0.0
print(f"seg={seg} window=[{t0},{t1}]")
for m in LogReader(rp):
    t = m.logMonoTime / 1e9
    if t < t0 - 0.2 or t > t1:
        continue
    w = m.which()
    if w == "modelV2":
        lv = m.modelV2.leadsV3
        s = " ".join(f"L{i}:p={float(lv[i].prob):.2f},x={float(lv[i].x[0]):6.2f},v={float(lv[i].v[0]):5.2f}"
                     for i in range(min(2, len(lv))))
        i = np.clip(np.searchsorted(vt, t, "right") - 1, 0, len(vt) - 1) if len(vt) else 0
        ve = vv[i] if len(vt) else float("nan")
        print(f"{t:.3f} modelV2  {s}  vEgo={ve:.2f}")
    elif w == "radarState":
        lo = m.radarState.leadOne
        print(f"{t:.3f} radarSt  pres={int(lo.present)} dRel={float(lo.dRel):6.2f} vRel={float(lo.vRel):6.2f} "
              f"vLead={float(lo.vLead):6.2f} radar={int(lo.radar)} mprob={float(lo.modelProb):.2f}")
    elif w == "radarTracks":
        pts = m.radarTracks.points
        s = " ".join(f"[d={float(p.dRel):6.2f},v={float(p.vRel):6.2f},y={float(p.yRel):5.2f},id={int(p.trackId)}]"
                     for p in pts)
        print(f"{t:.3f} radarTrk n={len(pts)} {s}")
    elif w == "selfdriveState":
        print(f"{t:.3f} sdState  enabled={int(m.selfdriveState.enabled)} active={int(m.selfdriveState.active)}")
    elif w == "longitudinalPlan":
        print(f"{t:.3f} longPlan a={float(m.longitudinalPlan.accels[0]):+.2f} src={m.longitudinalPlan.longitudinalPlanSource}")

