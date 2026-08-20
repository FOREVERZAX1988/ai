#!/usr/bin/env python3
"""qlog 快速扫描 0002-0005：定位高速段（v>70km/h）"""
import glob, sys, re
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

for pre in ["00000002", "00000003", "00000004", "00000005"]:
  qlogs = sorted(glob.glob(f"/data/media/0/realdata/{pre}--*--qlog.zst"))
  if not qlogs:
    qlogs = sorted(glob.glob(f"/data/media/0/realdata/{pre}--*/qlog.zst"))
  highs = []
  for q in qlogs:
    m = re.search(r"--(\d+)--qlog\.zst$", q)
    si = m.group(1) if m else "?"
    lr = LogReader(q)
    vmax = 0.0
    n = 0
    for msg in lr:
      if msg.which() == "carState":
        v = msg.carState.vEgo
        n += 1
        if v > vmax:
          vmax = v
    del lr
    if vmax > 70/3.6:
      highs.append((si, vmax*3.6, n))
  print(f"{pre}: {len(qlogs)} 段, 其中高速段(v>70) {len(highs)} 个")
  for si, vmax, n in highs[:15]:
    print(f"  段{si}: vmax={vmax:.0f}km/h 帧数~{n}")
