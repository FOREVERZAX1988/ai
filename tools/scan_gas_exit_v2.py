#!/usr/bin/env python3
"""修正扫描：检测"踩油门期间 enabled 退出"（不是松开后）
用户描述：踩油门（没踩刹车）→ 仪表盘灰色（巡航自动退出）——退出可能发生在踩油门过程中
逻辑：gas=1 连续时段内，enabled 从 True 变 False → 退出事件"""
import glob, sys
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

segs = sorted(glob.glob("/data/media/0/realdata/0000004f--*/rlog.zst"))
print(f"{'段':>2} {'踩油门起':>7} {'退出帧':>7} {'踩油时长s':>8} {'退出时v':>6}")
tot_events = 0
tot_exit = 0
for si in range(0, 7):
    lr = LogReader(segs[si])
    st = {"f": 0, "gas": 0, "en": 0, "pg": 0, "pe": 0, "v": 0.0}
    gas_start = None
    in_gas = False
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            cs = msg.carState
            st["gas"] = cs.gasPressed
            st["en"] = cs.cruiseState.enabled
            st["v"] = cs.vEgo
        # 踩油门开始
        if st["gas"] and not in_gas:
            gas_start = f
            in_gas = True
        # 踩油门期间 enabled 退出
        if in_gas and st["pe"] and not st["en"]:
            tot_events += 1
            tot_exit += 1
            print(f"{si:>2} {gas_start:>7} {f:>7} {(f-gas_start)/100:>8.2f} {st['v']*3.6:>6.0f}")
            # 本次 gas 时段结束（退出后重置）
            in_gas = False
            gas_start = None
        # 松开
        if in_gas and st["pg"] == 1 and st["gas"] == 0:
            tot_events += 1
            # 无退出（松开时 en 仍 True）
            in_gas = False
            gas_start = None
        st["pg"] = st["gas"]
        st["pe"] = st["en"]
        st["f"] += 1
    del lr
print(f"\n踩油门时段总数: {tot_events} | 期间退出: {tot_exit} ({100*tot_exit/max(tot_events,1):.0f}%)")
