#!/usr/bin/env python3
import sys, glob, collections
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/openpilot")
import numpy as np
from openpilot.tools.lib.logreader import LogReader

def parse(f):
    key = collections.Counter(); idx_by = collections.defaultdict(list)
    for m in LogReader(f):
        if m.which() != 'can': continue
        for c in m.can:
            if c.address == 780 and len(c.dat) >= 7:
                k = c.src
                key[k] += 1
                idx_by[k].append((((c.dat[3] | (c.dat[4] << 8)) & 0x3FF), int((c.dat[4] >> 5) & 7)))
    return key, idx_by

for rt in ['00000071', '00000072', '00000004', '00000002', '00000049']:
    fs = sorted(glob.glob(f'/data/media/0/realdata/{rt}--*/rlog.zst'))
    if not fs: continue
    f = fs[0]
    key, idx_by = parse(f)
    print(f"\n=== {rt} {f.split('/')[-2]} ===")
    for k in sorted(key):
        v = np.array(idx_by[k])
        print(f"  src={k:>4} n={key[k]:>7} idx_med={np.median(v[:,0]):>6.0f} zl={collections.Counter(v[:,1]).most_common(3)}")
