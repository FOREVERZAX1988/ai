#!/usr/bin/env python3
"""Probe undecoded CAN IDs 0x127(295) and 0x395(917) raw byte behavior.
Stats byte distributions, counters, checksum-like, and correlation with vEgo."""
import sys, glob
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
import numpy as np
from collections import Counter, defaultdict

TARGETS = {0x127: '0x127(295)', 0x395: '0x395(917)'}
ROUTES = [
    "/data/media/0/realdata/00000004--915ebf086f--20/rlog.zst",  # highway seg20
    "/data/media/0/realdata/00000049--ac8e2bc7b1--12/rlog.zst",  # city
]

# gather raw frames + vehspeed
frames = {a: [] for a in TARGETS}
vEgo_times = []  # collect vEgo sample near-frame by msg t
for p in ROUTES:
    try:
        lr = LogReader(p)
    except Exception as e:
        print("ERR", p, e); continue
    n=0
    for msg in lr:
        n+=1
        if n>40000: break
        if msg.which()=="can":
            for c in msg.can:
                if c.address in TARGETS and (c.src in (0,2) or True):
                    frames[c.address].append((msg.logMonoTime, bytes(c.dat).hex()))
        if "lr" in dir(): del lr

for aid, label in TARGETS.items():
    fr = frames.get(aid, [])
    print(f"\n===== {label} : {len(fr)} frames =====")
    if not fr: 
        print("no frames"); continue
    # DLC
    print("DLC dist:", Counter(len(bytes.fromhex(h)) for _,h in fr))
    # byte-value stats per position (first 16 frames raw, then ranges)
    print("\nFirst 8 frames raw:")
    for t,h in fr[:8]:
        print("  ", h)
    # per-byte: unique count, min, max, mode, entropy-ish
    data=[bytes.fromhex(h) for _,h in fr]
    dlc=len(data[0])
    print(f"\nPer-byte stats (dlc={dlc}, n={len(data)}):")
    print(f"{'byte':<5}{'unique':>7}{'min':>8}{'max':>8}{'chg%':>7}{'mode':>8}")
    for b in range(dlc):
        arr=np.array([d[b] for d in data])
        chg=np.mean(arr[1:]!=arr[:-1])*100
        mode=Counter(arr).most_common(1)[0]
        # rolling-averaged byte 0/1 (potential counter)
        print(f"  {b:<4}{len(np.unique(arr)):>6}{arr.min():>7}{arr.max():>7}{chg:>6.0f}%  mode={mode[0]}(x{mode[1]})")
