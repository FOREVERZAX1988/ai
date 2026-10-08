#!/usr/bin/env python3
"""检查 seg 的 rlog/qlog 里是否含原始总线帧（用于确认 idx 来源），并给出 idx 统计。"""
import sys
import collections
import numpy as np
sys.path.insert(0, "/data/openpilot")
sys.path.insert(0, "/data/openpilot/ai/tools")
from openpilot.tools.lib.logreader import LogReader  # noqa: E402

seg = sys.argv[1]
for kind in ("rlog", "qlog"):
    p = f"/data/media/0/realdata/{seg}/{kind}.zst"
    c = collections.Counter()
    for m in LogReader(p):
        c[m.which()] += 1
    bus = [k for k in c if k in ("can", "sendcan", "pandaStates")]
    print(f"{kind}: topics={len(c)} bus_topics={bus}")

sys.path.insert(0, "/data/openpilot/ai/tools")
from macan_route_lib_0910 import parse_segment  # noqa: E402
R = parse_segment(seg, use_cache=False)
if R is None:
    print("parse_segment=None")
else:
    idx = R["idx"]
    nz = idx[idx > 0]
    print(f"frames={len(idx)} idx>0 frames={len(nz)} ({100*len(nz)/max(len(idx),1):.1f}%) "
          f"idx range=[{nz.min() if len(nz) else 0},{nz.max() if len(nz) else 0}] "
          f"uniq={len(np.unique(nz))} v_ego_mean={np.mean(R['v_ego']):.2f} d_vis_nan={np.mean(~np.isfinite(R['d_vis'])):.2f}")
