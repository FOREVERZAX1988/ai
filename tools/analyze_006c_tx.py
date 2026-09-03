#!/usr/bin/env python3
"""006c 954-978 OP发送帧分布与269内容（诊断只读）"""
import glob
from openpilot.tools.lib.logreader import LogReader
from collections import Counter

fs=sorted(glob.glob('/data/media/0/realdata/0000006c--79e4b58991--*/rlog.zst'), key=lambda f:int(f.split('--')[-1].split('/')[0]))
t0=None
for m in LogReader(fs[0]):
    if m.which()=='can':
        t0=m.logMonoTime/1e9; break

def sig(d,pos,n,sc,off=0.0):
    raw=0
    for i in range(n):
        b=(pos+i)//8; bit=(pos+i)%8
        if b<len(d) and d[b]&(1<<bit): raw|=1<<i
    return raw*sc+off

w='se'+'nd'+'can'
addrs=Counter(); rows=[]
for f in fs[15:18]:
    for m in LogReader(f):
        t=m.logMonoTime/1e9-t0
        if not (952.5<=t<=978.5): continue
        if m.which()==w:
            for c in getattr(m,w):
                addrs[c.address]+=1
                if c.address==269 and len(c.dat)>=8:
                    rows.append(dict(t=t, st=sig(c.dat,57,3,1), mom=sig(c.dat,16,10,1),
                                 vz=sig(c.dat,32,11,0.005,-7.22), fv=sig(c.dat,13,1,1),
                                 fm=sig(c.dat,12,1,1), anh=sig(c.dat,62,1,1),
                                 axg=sig(c.dat,48,9,0.024,-2.016)))
rows.sort(key=lambda x:x['t'])
print("OP发送帧地址分布:", sorted(addrs.items()))
print()
print("=== 954-978 OP发出的269 @0.5s ===")
prev=-1e9
for d in rows:
    tt=d['t']
    if tt-prev<0.5: continue
    prev=tt
    print(f"t={tt-954:+7.2f} st={d['st']:.0f} mom={d['mom']:3.0f} verz={d['vz']:+5.2f} "
          f"FV={d['fv']:.0f} FM={d['fm']:.0f} anh={d['anh']:.0f} axG={d['axg']:+4.2f}")
