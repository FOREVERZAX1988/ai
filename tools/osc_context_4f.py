#!/usr/bin/env python3
"""振荡窗口上下文：段8 53440、段12 36700 —— aTgt跳变时 hasLead/vEgo/vSet/modelV2曲率"""
import glob, sys, math
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

segs = sorted(glob.glob("/data/media/0/realdata/0000004f--*/rlog.zst"))

def show(si, lo, hi, label):
    lr = LogReader(segs[si])
    st = {"f": 0, "v": 0.0, "vSet": 0.0, "aTgt": 0.0, "hasLead": False, "lead_d": -1.0, "lead_v": 0.0}
    print(f"\n===== {label} (段{si} 帧{lo}-{hi}) =====")
    print(f"{'帧':>6} {'v':>5} {'vSet':>5} | {'aTgt':>6} {'lead':>4} {'lead_d':>6} | {'lead_v':>5}")
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            cs = msg.carState
            st["v"] = cs.vEgo
            st["vSet"] = cs.cruiseState.speed * 3.6
        elif msg.which() == "longitudinalPlan":
            lp = msg.longitudinalPlan
            st["aTgt"] = lp.aTarget
            try:
                st["hasLead"] = lp.hasLead
            except Exception:
                pass
        elif msg.which() == "radarState":
            rs = msg.radarState
            try:
                pts = rs.points
                if len(pts):
                    ds = [p.d for p in pts if p.d > 0]
                    st["lead_d"] = min(ds) if ds else -1.0
            except Exception:
                pass
        if lo <= f <= hi and f % 10 == 0:
            print(f"{f:>6} {st['v']*3.6:>5.1f} {st['vSet']:>5.1f} | {st['aTgt']:>6.2f} {int(st['hasLead']):>4} {st['lead_d']:>6.1f}")
        st["f"] += 1
        if f > hi: break
    del lr

show(8, 53400, 53560, "段8 减速事件")
show(12, 36650, 37000, "段12 振荡区")
