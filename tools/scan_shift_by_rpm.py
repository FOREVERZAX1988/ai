#!/usr/bin/env python3
"""用转速突变检测PDK换挡, 与aEgo顿挫对照.
换挡候选: 转速在0.35s内变化>18% 且 车速>2m/s(排除静止), 记(时间,old_rpm,new_rpm)
顿挫: aEgo在0.1s内变化>1.0 m/s²
"""
import sys, os
BASE='/data/media/0/realdata'
ROUTE = sys.argv[1] if len(sys.argv)>1 else "00000071--363798636e"
segs = sorted([f'{BASE}/{d}/rlog.zst' for d in os.listdir(BASE)
      if d.startswith(ROUTE) and os.path.isfile(f'{BASE}/{d}/rlog.zst')])
print(f'扫描 {len(segs)} segs: {ROUTE}', flush=True)
from openpilot.tools.lib.logreader import LogReader
from collections import deque

# 时间序列
rpm_hist=deque()  # (t, rpm)
gear_ts=None; vEgo=0.0; last_ae=None
shifts=[]; jerks=[]; rpm_at_shift=[]
for si,f in enumerate(segs):
  try:
    rpm_hist.clear(); last_ae=None; vEgo=0.0
    for m in LogReader(f):
      w=m.which(); t=m.logMonoTime/1e9
      if w=='can':
        for c in m.can:
          if c.address==128 and len(c.dat)>=4:
            rpm=((c.dat[2])|(c.dat[3]<<8))*0.25
            rpm_hist.append((t,rpm))
      elif w=='carState':
        cs=m.carState; ae=cs.aEgo; vEgo=cs.vEgo
        # 顿挫检测
        if last_ae is not None and abs(ae-last_ae)>1.0:
          jerks.append((t,ae,last_ae))
        # 换挡检测: 新转速 vs 0.35s前
        while rpm_hist and t-rpm_hist[0][0]>0.35:
          rpm_hist.popleft()
        if rpm_hist and vEgo>2.0:
          t0,r0=rpm_hist[0]
          if r0>600 and abs(rpm_hist[-1][1]-r0)/r0>0.18 and rpm_hist[-1][0]-t0>0.1:
            shifts.append((t, r0, rpm_hist[-1][1], vEgo))
        last_ae=ae
    print(f'  seg{si} done: shifts累计{len(shifts)} jerks累计{len(jerks)}', flush=True)
  except Exception as e:
    print(f'  seg{si} {f} err {e}', flush=True)

print(f'\n=== 结果 ===', flush=True)
print(f'换挡候选(转速突变) {len(shifts)}, 顿挫 {len(jerks)}', flush=True)
# 匹配
match=sum(1 for s in shifts if any(abs(j[0]-s[0])<1.0 for j in jerks))
print(f'换挡后1s内有顿挫: {match}/{len(shifts)}  换挡无顿挫: {len(shifts)-match}/{len(shifts)}')
print(f'顿挫但非换挡引起: {len(jerks)-match}/{len(jerks)}')
print('\n=== 换挡候选样本(前25, 含是否顿挫) ===', flush=True)
shown=0
for s in shifts:
  has=[j for j in jerks if abs(j[0]-s[0])<1.0]
  mark='  <== 顿挫' if has else ''
  print(f'  t={s[0]:.1f}s rpm{s[1]:.0f}->{s[2]:.0f} vEgo={s[3]:.1f}{mark}', flush=True)
  shown+=1
  if shown>=25: break
