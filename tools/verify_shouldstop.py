#!/usr/bin/env python3
"""4e 段2 事件窗口：longitudinalPlan.shouldStop（planner 是否卡住没清）+ aTarget + LCS + accel
判断引入点：shouldStop=True 全程 → planner 层问题；shouldStop=False 但 LCS 卡 stopping → LoC 层问题"""
import glob, sys
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

segs = sorted(glob.glob("/data/media/0/realdata/0000004e--*/rlog.zst"))
lr = LogReader(segs[2])
st = {"f": 0, "gas": 0, "at": 0.0, "ss": None, "accel": 99.0, "lcs": -1, "v": 0.0}
print(f"{'帧':>6} {'gas':>3} {'v':>3} | {'aTgt':>5} {'shouldStop':>10} {'accel':>5} {'LCS':>18}")
for msg in lr:
    f = st["f"]
    if msg.which() == "carState":
        st["gas"] = msg.carState.gasPressed
        st["v"] = msg.carState.vEgo
    elif msg.which() == "longitudinalPlan":
        st["at"] = msg.longitudinalPlan.aTarget
        st["ss"] = msg.longitudinalPlan.shouldStop
    elif msg.which() == "carControl":
        st["accel"] = msg.carControl.actuators.accel
    elif msg.which() == "controlsState":
        st["lcs"] = msg.controlsState.longControlState
    if 34360 <= f <= 34600 and f % 10 == 0:
        print(f"{f:>6} {st['gas']:>3} {st['v']*3.6:>3.0f} | {st['at']:>5.2f} {str(st['ss']):>10} {st['accel']:>5.2f} {str(st['lcs']):>18}")
    st["f"] += 1
    if f > 34600: break
del lr
print("\n判断：shouldStop=True 全程 → planner 层问题（停车后未清）；False 但 LCS 卡 → LoC 层")
