#!/usr/bin/env python3
"""scan_st6_idx.py — st6事件 × Abstandsindex(ACC_02) 相关性验证
验证假设: 原厂在 Abstandsindex<200(近距离有目标) 时才校验 verz/axG 一致性, 不一致→st6
输出: 每个st6事件(st6前1帧)的idx + 全route的 idx<200 运行占比
用法: python3 scan_st6_idx.py ROUTE [ROUTE...]
"""
import sys, glob, os
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
    last_idx=None; prev_st=-1; events=[]; n269=0; nlt=0; n269_total=0
    try:
        for m in LogReader(sp):
            if m.which()!='can': continue
            for c in m.can:
                if c.src!=2 or len(c.dat)<8: continue
                d=bytes(c.dat)
                if c.address==780:
                    last_idx=gs(d,24,10)
                elif c.address==269:
                    st=int(gs(d,57,3))
                    n269_total+=1
                    if last_idx is not None:
                        n269+=1
                        if last_idx<200: nlt+=1
                    if st==6 and prev_st!=6 and prev_st>=0:
                        vz=gs(d,32,11,0.005,-7.22); axg=gs(d,48,9,0.024,-2.016)
                        events.append((int(prev_st), None if last_idx is None else int(last_idx), round(vz,2), round(axg,2)))
                    prev_st=st
    except Exception:
        pass
    return seg, events, n269, nlt
def main():
    routes=sys.argv[1:]
    if not routes: print("用法: scan_st6_idx.py ROUTE [ROUTE...]"); return
    for route in routes:
        segs=sorted(glob.glob(f"{BASE}/{route}--*--*/rlog.zst"))
        with Pool(4) as pool:
            res=pool.map(scan_seg,[(route,sp) for sp in segs])
        evs=[e for r in res for e in r[1]]
        n=sum(r[2] for r in res); nlt=sum(r[3] for r in res)
        print(f"\n===== {route}: st6事件 {len(evs)} | 运行中idx<200占比 {nlt*100//max(n,1)}% ({n}帧) =====")
        for e in evs:
            prev,idx,vz,axg=e
            mark="<200✓" if idx is not None and idx<200 else ">=200✗或无效"
            print(f"  st{prev}→6: idx={idx} ({mark}) verz={vz:+.2f} axG={axg:+.2f}")
if __name__=="__main__": main()
