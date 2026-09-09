#!/usr/bin/env python3
"""快速定位含行驶+刹车/顿挫的seg: 记录每seg最大车速和aEgo剧烈变化次数"""
import sys, os
BASE='/data/media/0/realdata'
segs = sorted([f'{BASE}/{d}/rlog.zst' for d in os.listdir(BASE)
      if d.startswith('00000071--363798636e') and os.path.isfile(f'{BASE}/{d}/rlog.zst')])
from openpilot.tools.lib.logreader import LogReader
for f in segs:
  mx=0; jerk=0; prev=None; sample=0
  try:
    for m in LogReader(f):
      if m.which()!='carState': continue
      cs=m.carState; mx=max(mx,cs.vEgo); sample+=1
      if prev is not None and abs(cs.aEgo-prev)>1.3: jerk+=1
      prev=cs.aEgo
  except Exception as e: print(f'  {f} err {e}')
  if mx>8:  # 只列行驶段
    print(f'  {os.path.basename(f.split("--")[1].split("--")[0] if "--" in f else f)}: maxV={mx:.1f} jerk={jerk} sample={sample}')
