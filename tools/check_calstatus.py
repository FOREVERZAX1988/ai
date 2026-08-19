#!/usr/bin/env python3
"""查自带校准（liveCalibration）calStatus 分布——区分'设备姿态校准'与'我们的重力向量标定'"""
import sys, glob
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

for seg in sorted(glob.glob("/data/media/0/realdata/00000049--ac8e2bc7b1--*/rlog.zst"))[-6:]:
    try:
        lr = LogReader(seg)
    except Exception as e:
        print(f"{seg}: 打开失败 {e}")
        continue
    stats = {}
    n = 0
    for msg in lr:
        n += 1
        if n > 30000: break
        if msg.which() == "liveCalibration":
            cs = msg.liveCalibration.calStatus
            stats[cs] = stats.get(cs, 0) + 1
            if len(stats) > 10: break
    del lr
    segname = seg.split("/")[-2][:22]
    print(f"{segname}: calStatus分布 {stats if stats else '(无liveCalibration)'}")
