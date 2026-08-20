#!/usr/bin/env python3
"""用正确的 57|3 位定义重扫"踩油门退出"事件：
4e 段2 帧34350-34700（原stO跳0事件）+ 4f 段1 帧14900-15350（退出事件）
确认：真实 stO/stS 序列（我们是否超驰、原厂是否真退出）"""
import glob, sys
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

def st57(d):
    # ACC_Status_ACC @57|3 (ACC_05, 269)
    return (d[7] >> 1) & 0x7

def st60(d):
    # ACC_01 的定义（错误用法对照）
    return (d[7] >> 4) & 0x7

def scan(route, si, T0, T1, label):
    segs = sorted(glob.glob(f"/data/media/0/realdata/{route}--*/rlog.zst"))
    lr = LogReader(segs[si])
    st = {"f": 0, "gas": 0, "en": 0, "stO57": -1, "stS57": -1, "stO60": -1, "stS60": -1}
    print(f"\n===== {label} =====")
    print(f"{'帧':>6} {'gas':>3} {'en':>3} | {'stO(57)':>6} {'stS(57)':>6} | {'stO(60旧)':>7} {'stS(60旧)':>7}")
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            cs = msg.carState
            st["gas"] = cs.gasPressed
            st["en"] = cs.cruiseState.enabled
        elif msg.which() == "can":
            for c in msg.can:
                if c.address == 269 and len(c.dat) >= 8:
                    d = bytes(c.dat)
                    if c.src == 128:
                        st["stO57"] = st57(d)
                        st["stO60"] = st60(d)
                    elif c.src == 2:
                        st["stS57"] = st57(d)
                        st["stS60"] = st60(d)
        if T0 <= f <= T1 and f % 15 == 0:
            print(f"{f:>6} {st['gas']:>3} {st['en']:>3} | {st['stO57']:>6} {st['stS57']:>6} | {st['stO60']:>7} {st['stS60']:>7}")
        st["f"] += 1
        if f > T1: break
    del lr

scan("0000004e", 2, 34350, 34700, "4e 段2 踩油门事件（34359起）")
scan("0000004f", 1, 14900, 15350, "4f 段1 踩油门事件（14977起）")
