import os
BASE='/data/media/0/realdata'
segs = sorted([d for d in os.listdir(BASE)
      if d.startswith('00000071--363798636e') and os.path.isfile(f'{BASE}/{d}/rlog.zst')])
print(f'seg数: {len(segs)}')
from openpilot.tools.lib.logreader import LogReader
for si,f in enumerate(segs):
  mx=0; jerk=0; prev=None; N=0
  try:
    for m in LogReader(f"{BASE}/{f}/rlog.zst"):
      if m.which()!='carState': continue
      cs=m.carState; mx=max(mx,cs.vEgo); N+=1
      if prev is not None and abs(cs.aEgo-prev)>1.3: jerk+=1
      prev=cs.aEgo
  except Exception as e: pass
  print(f'  seg{si} {f[-2:]}: maxV={mx:.1f} jerk={jerk} N={N}')
