#!/usr/bin/env python3
"""第一段（段0-6，补偿全关）踩油门→巡航退出事件扫描：
检测：gasPressed 1→0 后 3 秒内 cruiseState.enabled 变 False（巡航退出/仪表盘灰）
输出：段/踩油门帧/松开帧/踩油门时长/退出?/退出帧"""
import glob, sys
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

segs = sorted(glob.glob("/data/media/0/realdata/0000004f--*/rlog.zst"))

print(f"{'段':>2} {'踩油门帧':>7} {'松开帧':>7} {'时长s':>5} {'退出?':>5} {'退出帧':>7}")
events = []
for si in range(0, 7):
    lr = LogReader(segs[si])
    st = {"f": 0, "gas": 0, "en": 0, "pg": 0, "pe": 0}
    gas_start = None
    pending = None  # (si, gas_start, gas_end)
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            cs = msg.carState
            st["gas"] = cs.gasPressed
            st["en"] = cs.cruiseState.enabled
        # 踩油门开始
        if st["gas"] and st["pg"] == 0:
            gas_start = f
        # 松开
        if st["pg"] == 1 and st["gas"] == 0 and gas_start is not None:
            pending = (si, gas_start, f)
            gas_start = None
        # 检查 pending 事件是否退出（3秒窗口）
        if pending is not None:
            ps, pg0, pg1 = pending
            if f - pg1 > 300:
                # 3 秒内没退出
                events.append((ps, pg0, pg1, False, None))
                pending = None
            elif st["pe"] and not st["en"] and f > pg1:
                # 退出了
                events.append((ps, pg0, pg1, True, f))
                pending = None
        st["pg"] = st["gas"]
        st["pe"] = st["en"]
        st["f"] += 1
    del lr

n_exit = 0
for e in events:
    si, g0, g1, exited, ef = e
    dur = (g1 - g0) / 100.0
    if exited:
        n_exit += 1
    print(f"{si:>2} {g0:>7} {g1:>7} {dur:>5.2f} {'✅退出' if exited else '否':>5} {ef if ef else '':>7}")
print(f"\n踩油门事件总数: {len(events)} | 退出: {n_exit} ({100*n_exit/max(len(events),1):.0f}%)")
