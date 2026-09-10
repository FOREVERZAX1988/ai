#!/usr/bin/env python3
"""v2 扫描：idx 强制 bus2(src==2) + 视觉前车速度 + 原厂前车速度(ACC_04)。
用于 (a) 分支隔离复核 (b) 速度一致性门控 (c) idx 全段平滑性(分段?)检验。"""
import sys, glob, os
sys.path.insert(0,"/data/openpilot"); sys.path.insert(0,"/data/openpilot/openpilot")
import numpy as np
from openpilot.tools.lib.logreader import LogReader

OUT="/data/openpilot/ai/tools/.scan2"
os.makedirs(OUT, exist_ok=True)

def parse(f):
    rows=[]
    idx=0.0; zl=0; rv=np.nan; vwh=0.0; ve=0.0
    for m in LogReader(f):
        w=m.which()
        if w=='can':
            for c in m.can:
                if c.src!=2: continue
                d=c.dat
                if c.address==780 and len(d)>=8:
                    idx=float((d[3]|(d[4]<<8))&0x3FF)
                    zl=int((d[4]>>5)&7)
                elif c.address==804 and len(d)>=8:
                    r=((d[5]|(d[6]<<8))&0x3FF)*0.32
                    rv=np.nan if r>320.0 else r
                elif c.address==259 and len(d)>=8:
                    s=(((d[2]|(d[3]<<8))&0xFFF)+(((d[3]>>4)|(d[4]<<4))&0xFFF)+((d[5]|(d[6]<<8))&0xFFF)+(((d[6]>>4)|(d[7]<<4))&0xFFF))*0.1
                    vwh=s/4/3.6
        elif w=='carState':
            ve=float(m.carState.vEgo)
        elif w=='modelV2':
            ld=m.modelV2.leadsV3
            if len(ld)>0 and len(ld[0].x)>0:
                l0=ld[0]
                rows.append((idx, zl, rv, vwh if vwh>1.0 else ve, float(l0.x[0]), float(l0.v[0]), float(l0.prob)))
    return rows

if __name__=='__main__':
    for rt in sys.argv[1:]:
        fs=sorted(glob.glob(f"/data/media/0/realdata/{rt}--*/rlog.zst"))
        allr=[]
        for f in fs: allr.extend(parse(f))
        a=np.array(allr, dtype=float) if allr else np.zeros((0,7))
        np.savez(f"{OUT}/{rt}.npz", idx=a[:,0], zl=a[:,1], rv=a[:,2], v=a[:,3], dv=a[:,4], vv=a[:,5], p=a[:,6])
        m=(a[:,6]>0.5)&(a[:,0]>10)&(a[:,0]<1021)&(a[:,3]>1.0)&(a[:,4]>0)
        print(f"{rt}: frames={len(a)} 有效(n={m.sum()}) idx中位={np.median(a[m,0]) if m.sum() else -1:.0f} zl分布={dict(zip(*np.unique(a[m,1],return_counts=True))) if m.sum() else {}}", flush=True)
