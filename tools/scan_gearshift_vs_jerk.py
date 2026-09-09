#!/usr/bin/env python3
"""验证Dennis假设：换挡是否造成顿挫(127全覆盖版)。
实际档位 = address 129 byte1低4bit (0-15, 对应MO_Istgang实际挡).
转速 = address 128 byte2..byte3 bit16|16 *0.25.
与 aEgo 突变(顿挫) 时间对齐检测.
"""
import sys, os
from collections import defaultdict
ROUTE = sys.argv[1] if len(sys.argv)>1 else "00000071--363798636e"
BASE='/data/media/0/realdata'
segs = sorted([f'{BASE}/{d}/rlog.zst' for d in os.listdir(BASE)
      if d.startswith(ROUTE) and os.path.isfile(f'{BASE}/{d}/rlog.zst')])
print(f'扫描 {len(segs)} segs: {ROUTE}', flush=True)
from openpilot.tools.lib.logreader import LogReader

gear_changes=[]  # (t, old, new, vEgo)
jerk_events=[]   # (t, aEgo, paEgo)
last_gear=None; gear_ts=None; last_ae=None; vEgo=0.0
for f in segs:
  try:
    last_gear=gear_ts=None
    for m in LogReader(f):
      w=m.which(); t=m.logMonoTime/1e9
      if w=='can':
        cur=None
        for c in m.can:
          if c.address==129 and len(c.dat)>=8:
            cur=c.dat[1]&0xF; gear_ts=t
        if cur is not None:
          if last_gear is not None and cur!=last_gear:
            gear_changes.append((t,last_gear,cur,vEgo))
          last_gear=cur
      elif w=='carState':
        cs=m.carState; ae=cs.aEgo; vEgo=cs.vEgo
        if last_ae is not None and abs(ae-last_ae)>1.2:
          jerk_events.append((t,ae,last_ae))
        last_ae=ae
  except Exception as e:
    print(f'  {f} err {e}', flush=True)

print(f'换挡事件 {len(gear_changes)}, aEgo突变 {len(jerk_events)}', flush=True)
# 匹配: 换挡前后1.0s 有顿挫
print('\n=== 换挡时刻附近1s是否有顿挫 ===', flush=True)
matched=[g for g in gear_changes if any(abs(j[0]-g[0])<1.0 for j in jerk_events)]
print(f'换挡但1s无顿挫: {len(gear_changes)-len(matched)} 次, 换挡且1s有顿挫: {len(matched)} 次')
print('\n=== 不匹配的换挡(近1s无顿挫)样本(前20) ===', flush=True)
shown=0
for g in gear_changes:
  if not any(abs(j[0]-g[0])<1.0 for j in jerk_events):
    print(f'  t={g[0]:.1f}s 档{g[1]}->{g[2]} vEgo={g[3]:.1f}m/s'); shown+=1
    if shown>=20: break
print('\n=== 顿挫事件(前25) + 是否临近换挡 ===', flush=True)
shown=0
for j in jerk_events:
  ng=[g for g in gear_changes if abs(g[0]-j[0])<1.0]
  mark='  <-- 临近换挡' if ng else ''
  print(f'  t={j[0]:.1f}s aEgo {j[2]:+.2f}->{j[1]:+.2f}{mark}', flush=True)
  shown+=1
  if shown>=25: break
