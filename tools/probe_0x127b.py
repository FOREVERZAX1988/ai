#!/usr/bin/env python3
import sys, glob
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
import numpy as np
from collections import Counter, defaultdict

ROUTES = ["/data/media/0/realdata/00000004--915ebf086f--20/rlog.zst",
          "/data/media/0/realdata/00000049--ac8e2bc7b1--12/rlog.zst"]
TARGETS={0x127,0x395}
data=defaultdict(list)   # (aid,src) -> list of (t,hex)
vego=defaultdict(list)   # t -> vEgo*m/s(km/h)
for p in ROUTES:
    try: lr=LogReader(p)
    except Exception as e: print("ERR",p,e); continue
    for msg in lr:
        if msg.which()=="can":
            for c in msg.can:
                if c.address in TARGETS:
                    data[(c.address,c.src)].append((msg.logMonoTime,bytes(c.dat).hex()))
        elif msg.which()=="carState" and hasattr(msg.carState,'vEgo'):
            vego[msg.logMonoTime]=msg.carState.vEgo*3.6
    del lr

for (aid,src),fr in sorted(data.items()):
    fr.sort()
    d=[bytes.fromhex(h) for _,h in fr]
    dlc=len(d[0]); n=len(d)
    print(f"\n=== 0x{aid:X} src={src}: n={n} dlc={dlc} ===")
    print("first 5:", [h for _,h in fr[:5]])
    for b in range(dlc):
        arr=np.array([x[b] for x in d])
        print(f"  b{b}: uniq={len(np.unique(arr))} min={arr.min()} max={arr.max()} chg%={np.mean(arr[1:]!=arr[:-1])*100:.0f}")
    # counter test on b1 (0x395): per-frame delta
    if 0x395==aid and dlc>1:
        b1=np.array([x[1] for x in d])
        deltas=b1[1:]-b1[:-1]
        print("  b1 delta dist:", {int(k):int(v) for k,v in Counter(deltas).most_common(6)})
    # checksum test: check if any byte correlates as XOR of others
    if n>20:
        # coarse: for each byte, correlation with vEgo interpolated
        ts=[t for t,_ in fr]; vv=[]
        for t in ts:
            # nearest vego
            near=min(vego.items(), key=lambda kv:abs(kv[0]-t)) if vego else (t,0)
            vv.append(near[1])
        vv=np.array(vv)
        for b in range(dlc):
            arr=np.array([x[b] for x in d])
            if np.std(arr)>0:
                cc=np.corrcoef(arr,vv)[0,1]
                if abs(cc)>0.5: print(f"  *b{b} corr with vEgo={cc:.2f}")
