#!/usr/bin/env python3
"""无车异常减速源定位：段8 53430 / 段12 36650 —— modelV2 leadsV3（视觉目标）+ position 曲率"""
import glob, sys, math
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

segs = sorted(glob.glob("/data/media/0/realdata/0000004f--*/rlog.zst"))

def curvature_from_position(pos):
    """从 modelV2.position 多项式算最近点曲率 (1/m)"""
    try:
        x = pos.x[0]; y = pos.y[0]
        dy = pos.y[1] / (2 * pos.x[1]) if pos.x[1] else 0.0
        # 位置多项式 y = c0 + c1*x + c2*x²（capnp 存的系数顺序 x0..x4 / y0..y4）
        c0, c1 = y[0], y[1]
        ddy = 2 * y[2] if len(y) > 2 else 0.0
        curv = ddy / (1 + c1 * c1) ** 1.5
        return curv
    except Exception:
        return 0.0

def show(si, lo, hi, label):
    lr = LogReader(segs[si])
    st = {"f": 0, "v": 0.0, "aTgt": 0.0, "v_lead": -1.0, "d_lead": -1.0, "curv": 0.0}
    print(f"\n===== {label} (段{si} 帧{lo}-{hi}) =====")
    print(f"{'帧':>6} {'v':>5} | {'aTgt':>6} | {'visLead_d':>8} {'visLead_v':>7} | {'curv(1/m)':>8} | {'R(m)':>7}")
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            st["v"] = msg.carState.vEgo
        elif msg.which() == "longitudinalPlan":
            st["aTgt"] = msg.longitudinalPlan.aTarget
        elif msg.which() == "modelV2":
            mv = msg.modelV2
            try:
                leads = mv.leadsV3
                if len(leads) > 0:
                    st["d_lead"] = leads[0].distance if hasattr(leads[0], 'distance') else -1
                    st["v_lead"] = leads[0].velocity if hasattr(leads[0], 'velocity') else -1
                else:
                    st["d_lead"] = -1.0; st["v_lead"] = -1.0
            except Exception:
                pass
            try:
                st["curv"] = curvature_from_position(mv.position)
            except Exception:
                pass
        if lo <= f <= hi and f % 20 == 0:
            r = 1 / st["curv"] if abs(st["curv"]) > 1e-5 else 0
            print(f"{f:>6} {st['v']*3.6:>5.1f} | {st['aTgt']:>6.2f} | {st['d_lead']:>8.1f} {st['v_lead']*3.6:>7.1f} | {st['curv']:>8.5f} | {r:>7.0f}")
        st["f"] += 1
        if f > hi: break
    del lr

show(8, 53420, 53540, "段8 异常减速")
show(12, 36650, 36950, "段12 低速减速")
