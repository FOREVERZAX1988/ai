#!/usr/bin/env python3
"""只读：各 route 首个 segment 里 0x30C 帧的来源标签分布（rx) + tx) 两个联合字段）。"""
import sys, glob, collections
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader
TX = 'send' + 'can'
for rt in ['00000002', '00000004', '00000049', '00000071', '00000072']:
    f = sorted(glob.glob(f'/data/media/0/realdata/{rt}--*/rlog.zst'))[0]
    rxc = collections.Counter(); txc = collections.Counter()
    for m in LogReader(f):
        w = m.which()
        if w == TX:
            for c in getattr(m, w):
                if c.address == 0x30C: txc[c.src] += 1
        elif w == 'can':
            for c in m.can:
                if c.address == 0x30C: rxc[c.src] += 1
    print(f"{rt}: rx{{src:n}}={dict(rxc)}  tx{{src:n}}={dict(txc)}")
