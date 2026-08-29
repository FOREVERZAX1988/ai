#!/usr/bin/env python3
"""route_global_offset.py — 计算 route 内各 segment 起始的全局时间偏移
对每个指定 segment，读其 rlog 第一条 msg 的 logMonoTime;
route 全局秒 = seg首帧偏移(相对route首帧) + 段内秒
用法: python3 route_global_offset.py ROUTE_PREFIX SEGNO [SEGNO..]
"""
import sys, os, glob
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
BASE="/data/media/0/realdata"
pref=sys.argv[1]
seglist=sys.argv[2:]
# route 起点 = 段0 首帧
seg0=os.path.join(glob.glob(f"{BASE}/{pref}--*--0/rlog.zst")[0])
route0=None
for msg in LogReader(seg0):
    route0=msg.logMonoTime/1e9; break
print(f"ROUTE {pref} 起点(rel0) t0={route0:.3f}s")
for s in seglist:
    p=glob.glob(f"{BASE}/{pref}--*--{s}/rlog.zst")
    if not p: print(f"[{s}] 无"); continue
    for msg in LogReader(p[0]):
        off=(msg.logMonoTime/1e9)-route0
        print(f"seg {s}: 起点全局偏移 = {off:.0f}s = {int(off//60)}分{off%60:.0f}秒")
        break
