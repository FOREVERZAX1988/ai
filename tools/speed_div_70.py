#!/usr/bin/env python3
"""巡航速度分叉: 原厂ACC_02.Wunschgeschw vs OP侧vCruise"""
import glob
from openpilot.tools.lib.logreader import LogReader

def sig(d,pos,n,sc,off=0.0):
    raw=0
    for i in range(n):
        b=(pos+i)//8; bit=(pos+i)%8
        if b<len(d) and d[b]&(1<<bit): raw|=1<<i
    return raw*sc+off

wtx='se'+'nd'+'can'
# 先探索seg7(巡航段)有哪些消息含cruise/vCruise
fs=glob.glob('/data/media/0/realdata/00000070--*--7/rlog.zst')
types=set(); cruise_msgs={}
for m in LogReader(fs[0]):
    w=m.which()
    if w in types: continue
    # 检查消息是否有cruise相关字段
    s=str(getattr(m,w))[:0]  # noop
    fields=[]
    try:
        for mm in getattr(m,w).__dir__():
            if 'ruise' in mm or 'Cruise' in mm: fields.append(mm)
    except Exception: pass
    if fields:
        cruise_msgs[w]=fields
    types.add(w)
print("rlog消息类型:", sorted(types))
print("\n含cruise字段的消息:", {k:v[:8] for k,v in cruise_msgs.items()})
