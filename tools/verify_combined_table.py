#!/usr/bin/env python3
"""组合表验证：低速区(idx<234)实测点 + 高速区(>=234)原11点表（2026-09-02）
表源：recalibrate_full.py 混合表v2(日志解析)；验证：6-route留出集(每route后2段,子进程隔离)
用法: python3 ai/tools/verify_combined_table.py
"""
import glob, re, statistics
from collections import defaultdict
from multiprocessing import Process, Queue

ROUTES = ["00000002", "00000003", "00000004", "00000049", "00000065", "00000066"]
OLD_IDX = [100, 106, 122, 168, 234, 271, 363, 380, 389, 401, 420]
OLD_T   = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 6.0]

def read_seg(f, q):
    from openpilot.tools.lib.logreader import LogReader
    out=[]; cur_idx=cur_v=cur_prob=0.0; cur_d=None
    for m in LogReader(f):
        w=m.which()
        if w=='can':
            for c in m.can:
                if c.src!=2 or c.address!=780 or len(c.dat)<7: continue
                cur_idx=(c.dat[3]|(c.dat[4]<<8))&0x3FF
        elif w=='carState':
            cur_v=float(m.carState.vEgo)
        elif w=='modelV2':
            try:
                ld=m.modelV2.leadsV3
                if len(ld)>0:
                    cur_prob=float(ld[0].prob)
                    cur_d=float(ld[0].x[0]) if len(ld[0].x)>0 else None
                else: cur_prob=0.0; cur_d=None
            except Exception: cur_prob=0.0; cur_d=None
            if cur_idx and 0<cur_idx<1021 and cur_prob>0.5 and cur_d and 2.0<cur_d<300.0 and cur_v>2.0:
                out.append((int(cur_idx), cur_v, cur_d))
    q.put(out)

def read_seg_safe(f):
    q=Queue(); p=Process(target=read_seg,args=(f,q),daemon=True)
    p.start(); p.join(40)
    if p.is_alive(): p.terminate(); p.join(); return []
    try: return q.get(timeout=5)
    except Exception: return []

# 解析混合表v2
txt=open('/tmp/recal_full.log').read()
m1=re.search(r'_macan_abstands_idx = \[ ([^\]]+) \]', txt)
m2=re.search(r'_macan_abstands_t   = \[ ([^\]]+) \]', txt)
MX=[int(x) for x in m1.group(1).split(',')]
MY=[float(x) for x in m2.group(1).split(',')]

# 组合表: <234 实测点, >=234 原表
comb=[(x,y) for x,y in zip(MX,MY) if x<234 and y>0.05]+[(x,y) for x,y in zip(OLD_IDX,OLD_T) if x>=234]
comb.sort()
print(f"组合表点数: {len(comb)} (低速实测{sum(1 for x,_ in comb if x<234)} + 高速原表{sum(1 for x,_ in comb if x>=234)})")

val=[]
for r in ROUTES:
    fs=sorted(glob.glob(f'/data/media/0/realdata/{r}--*--*/rlog.zst'))
    for f in fs[-2:]:
        val+=read_seg_safe(f)
print(f"验证集={len(val)}")

def interp(x):
    xs=[p[0] for p in comb]; ys=[p[1] for p in comb]
    if x<=xs[0]: return ys[0]
    if x>=xs[-1]: return ys[-1]
    for i in range(len(xs)-1):
        if xs[i]<=x<=xs[i+1]:
            return ys[i]+(ys[i+1]-ys[i])*(x-xs[i])/(xs[i+1]-xs[i])
    return ys[-1]

def stats(lo=None,hi=None):
    e=[]
    for idx,v,d in val:
        if lo is not None and idx<lo: continue
        if hi is not None and idx>=hi: continue
        dp=interp(idx)*max(v,5.0); dr=d-1.0
        if dr>2: e.append(abs(dp-dr)/dr)
    return statistics.median(e) if e else -1

print(f"\n=== 组合表验证（留出集 {len(val)}） ===")
print(f"低速<234: {stats(None,234)*100:.2f}%")
print(f"高速>=234: {stats(234,None)*100:.2f}%")
print(f"全部: {stats()*100:.2f}%")
print("\n=== 组合表（idx↔时距秒，可直接替换） ===")
print("_macan_abstands_idx = [", ", ".join(str(p[0]) for p in comb), "]")
print("_macan_abstands_t   = [", ", ".join(f"{p[1]:.3f}" for p in comb), "]")
