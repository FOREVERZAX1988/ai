#!/usr/bin/env python3
import sys
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
import numpy as np
from collections import Counter, defaultdict

P="/data/media/0/realdata/00000004--915ebf086f--20/rlog.zst"
data=defaultdict(list)
vego=[]
for msg in LogReader(P):
    if msg.which()=="can":
        for c in msg.can:
            if c.address in (0x127,0x395):
                data[(c.address,c.src)].append((msg.logMonoTime,bytes(c.dat)))
    elif msg.which()=="carState":
        vego.append((msg.logMonoTime,msg.carState.vEgo*3.6))

vego=np.array(sorted(vego),dtype=np.float64)
def v_at(t):
    if len(vego)==0: return np.nan
    i=np.searchsorted(vego[:,0],t)
    i=min(max(i,0),len(vego)-1)
    return vego[i,1]

for (aid,src),fr in sorted(data.items()):
    fr.sort()
    d=[h for _,h in fr]
    dlc=len(d[0]); n=len(d)
    print(f"\n=== 0x{aid:X} src={src}: n={n} dlc={dlc} ===")
    for b in range(dlc):
        arr=np.array([x[b] for x in d])
        print(f"  b{b}: uniq={len(np.unique(arr))} min={arr.min()} max={arr.max()} chg%={np.mean(arr[1:]!=arr[:-1])*100:.0f} mode={Counter(arr).most_common(1)[0]}")
    if aid==0x395 and dlc>1:
        b1=np.array([x[1] for x in d]); delt=b1[1:]-b1[:-1]
        print("  b1 delta:", {int(k):int(v) for k,v in Counter(delt).most_common(6)})
