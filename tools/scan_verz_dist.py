#!/usr/bin/env python3
"""scan_verz_dist.py — 超驰(st=4)时段 verz 符号 × 前车距离(ACC_Abstandsindex) 分组统计
验证假设: verz正值时前车距离 > verz负值时前车距离
用法: python3 scan_verz_dist.py ROUTE [ROUTE...]
数据源: bus2 原厂帧 ACC_02(780) Abstandsindex(24|10, 索引越大=越远)
        ACC_04(804) Geschw_Zielfahrzeug(40|10 @0.32, 无目标=327.36)
        ACC_05(269) st(57|3) verz(32|11 @0.005,-7.22)
"""
import sys, glob, os, re, statistics
sys.path.insert(0,"/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
from multiprocessing import Pool
BASE="/data/media/0/realdata"
def gs(d,sl,ln,sc=1.0,of=0.0):
    if len(d)<=(sl+ln-1)//8: return 0
    v=0
    for i in range(ln):
        b=(sl+i)//8; bt=(sl+i)%8
        if d[b]&(1<<bt): v|=(1<<i)
    return v*sc+of
def scan_seg(arg):
    route,sp=arg
    seg=os.path.basename(os.path.dirname(sp)).split('--')[-1]
    idx=0; gv=327.36
    g={'pos':[], 'neg':[], 'zero':[]}
    try:
        for m in LogReader(sp):
            if m.which()!='can': continue
            for c in m.can:
                if c.src!=2 or len(c.dat)<8: continue
                d=bytes(c.dat)
                if c.address==780:
                    idx=gs(d,24,10)   # 距离索引(1近~1023远)
                elif c.address==804:
                    gv=gs(d,40,10,0.32)  # 目标车速
                elif c.address==269:
                    st=int(gs(d,57,3))
                    if st==4:
                        vz=gs(d,32,11,0.005,-7.22)
                        key='pos' if vz>0.05 else ('neg' if vz<-0.05 else 'zero')
                        g[key].append((idx, gv))
    except Exception:
        pass
    return seg, g
def stat(vals):
    if not vals: return "-"
    v=sorted(vals)
    return f"min={v[0]} p25={v[len(v)//4]} med={v[len(v)//2]} p75={v[3*len(v)//4]} max={v[-1]} (n={len(v)})"
def main():
    routes=sys.argv[1:]
    if not routes: print("用法: scan_verz_dist.py ROUTE [ROUTE...]"); return
    for route in routes:
        segs=sorted(glob.glob(f"{BASE}/{route}--*--*/rlog.zst"))
        with Pool(4) as pool:
            res=pool.map(scan_seg,[(route,sp) for sp in segs])
        G={'pos':[], 'neg':[], 'zero':[]}
        for seg,g in res:
            for k in G: G[k]+=g[k]
        print(f"\n===== {route}: 超驰(st=4) verz符号 × 前车距离索引 =====")
        for k in ['pos','neg','zero']:
            idxs=[x[0] for x in G[k]]
            gvs=[x[1] for x in G[k] if x[1]<320]
            print(f"[verz{k:>4}] n={len(G[k])}")
            print(f"    距离索引: {stat(idxs)}")
            print(f"    目标车速: {stat(gvs)}")
        # 直接对比 pos vs neg
        p=[x[0] for x in G['pos']]; n=[x[0] for x in G['neg']]
        if p and n:
            pm=statistics.median(p); nm=statistics.median(n)
            print(f"→ verz正值中位距离索引={pm} vs verz负值中位距离索引={nm} → {'正值更远 ✓(假设成立)' if pm>nm else '负值更远/相当 (假设不成立)'}")
if __name__=="__main__": main()
