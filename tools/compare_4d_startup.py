#!/usr/bin/env python3
"""对比 4d vs 4e/4f 的"停车+踩油门"场景：
4d（0816）踩油门能起步（车动）——4e/4f（0820）车不动（shouldStop卡True）
找差异：shouldStop/aTgt/LCS/accel 在踩油门后的演变
4d 找停车→踩油门→车动的窗口（vEgo从0变>0.5）"""
import glob, sys
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

def find_4d_startup():
    """4d 里找：停车(en+v<0.1) → 踩油门 → 车动(v>0.5) 的窗口"""
    segs = sorted(glob.glob("/data/media/0/realdata/0000004d--*--rlog.zst"))
    for si in range(len(segs)):
        lr = LogReader(segs[si])
        st = {"f": 0, "gas": 0, "en": 0, "v": 0.0, "pg": 0}
        gas_start = None
        moved = None
        for msg in lr:
            f = st["f"]
            if msg.which() == "carState":
                cs = msg.carState
                st["gas"] = cs.gasPressed
                st["en"] = cs.cruiseState.enabled
                st["v"] = cs.vEgo
                if gas_start is not None and moved is None and st["v"] > 0.5:
                    moved = f
            if st["gas"] and st["pg"] == 0 and st["en"] and st["v"] < 0.1:
                gas_start = f
            if gas_start is not None and moved is not None:
                del lr
                return si, gas_start, moved
            if gas_start is not None and st["pg"] == 1 and st["gas"] == 0 and moved is None:
                gas_start = None
            st["pg"] = st["gas"]
            st["f"] += 1
        del lr
    return None, None, None

si, g0, g1 = find_4d_startup()
print(f"4d 停车踩油门→车动窗口: 段{si} 踩油门@{g0} 车动@{g1}" if g0 else "4d 未找到（可能4d没有停车踩油门起步场景？）")

if g0:
    T0, T1 = g0 - 50, g1 + 100
    segs = sorted(glob.glob("/data/media/0/realdata/0000004d--*--rlog.zst"))
    lr = LogReader(segs[si])
    st = {"f": 0, "gas": 0, "en": 0, "v": 0.0, "at": 0.0, "ss": None, "accel": 99.0, "lcs": -1}
    print(f"{'帧':>6} {'gas':>3} {'v':>4} | {'aTgt':>5} {'shouldStop':>10} {'accel':>5} {'LCS':>18}")
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            cs = msg.carState
            st["gas"] = cs.gasPressed; st["en"] = cs.cruiseState.enabled; st["v"] = cs.vEgo
        elif msg.which() == "longitudinalPlan":
            st["at"] = msg.longitudinalPlan.aTarget
            st["ss"] = msg.longitudinalPlan.shouldStop
        elif msg.which() == "carControl":
            st["accel"] = msg.carControl.actuators.accel
        elif msg.which() == "controlsState":
            st["lcs"] = msg.controlsState.longControlState
        if T0 <= f <= T1 and f % 10 == 0:
            print(f"{f:>6} {st['gas']:>3} {st['v']*3.6:>4.0f} | {st['at']:>5.2f} {str(st['ss']):>10} {st['accel']:>5.2f} {str(st['lcs']):>18}")
        st["f"] += 1
        if f > T1: break
    del lr
