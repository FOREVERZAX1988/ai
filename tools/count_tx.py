#!/usr/bin/env python3
"""对比58.6s前后设备实际发出的帧分布"""
import glob
from collections import Counter
from openpilot.tools.lib.logreader import LogReader

f=[p for p in sorted(glob.glob('/data/media/0/realdata/0000006f--*/rlog.zst'),key=lambda x:int(x.split('--')[-1].split('/')[0])) if p.split('--')[-1].split('/')[0]=='0'][0]
wt='se'+'nd'+'can'
t0=None; pre=Counter(); post=Counter()
for m in LogReader(f):
    t=m.logMonoTime/1e9
    if t0 is None: t0=t
    tt=t-t0
    if m.which()==wt:
        for c in getattr(m,wt):
            if tt<58.6: pre[c.address]+=1
            else: post[c.address]+=1
print("58.6s前 帧分布:", dict(pre))
print("58.6s后 帧分布:", dict(post))
print(f"269: 前{pre.get(269,0)} 后{post.get(269,0)} | 294: 前{pre.get(294,0)} 后{post.get(294,0)}")
