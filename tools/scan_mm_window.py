#!/usr/bin/env python3
"""scan_mm_window.py — 原厂监管窗口(idx阈值)反向验证
假设: 原厂只在 idx<200 时校验 verz/axG 一致性(持续差异→st6), idx≥200 放任
输出: 每route汇总 — idx<200 vs idx≥200 的 OP≠原厂差异帧数与st6次数
用法: python3 scan_mm_window.py ROUTE [ROUTE...]
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
    last_idx=None; last_vz=None; last_axg=None; prev_st=-1
    w1n=w1d=w2n=w2d=st6=0; first_diff=None
    for m in LogReader(sp):
        if m.which()!='can': continue
        for c in m.can:
            if len(c.dat)<8: continue
            d=bytes(c.dat)
            if c.src==2 and c.address==780:
                last_idx=gs(d,24,10)
            elif c.src==2 and c.address==269:
                last_vz=gs(d,32,11,0.005,-7.22); last_axg=gs(d,48,9,0.024,-2.016)
                st=int(gs(d,57,3))
                if st==6 and prev_st!=6 and prev_st>=0: st6+=1
                prev_st=st
            elif c.src==128 and c.address==269 and last_idx is not None and last_vz is not None:
                vz=gs(d,32,11,0.005,-7.22); axg=gs(d,48,9,0.024,-2.016)
                dv=abs(vz-last_vz); da=abs(axg-last_axg)
                if dv>0.5 or da>0.3:
                    if last_idx<200: w1n+=1; w1d+=1
                    else: w2n+=1; w2d+=1
                    if first_diff is None and last_idx>=200: first_diff=int(last_idx)
    return seg,w1d,w2d,w2n,st6,first_diff
def main():
    routes=sys.argv[1:]
    if not routes: print("用法: scan_mm_window.py ROUTE [ROUTE...]"); return
    for route in routes:
        segs=sorted(glob.glob(f"{BASE}/{route}--*--*/rlog.zst"))
        with Pool(4) as pool:
            res=pool.map(scan_seg,[(route,sp) for sp in segs])
        W1=sum(r[1] for r in res); W2=sum(r[2] for r in res); st6s=sum(r[4] for r in res)
        fd=sorted([r[5] for r in res if r[5] is not None])
        print(f"{route}: idx<200差异帧={W1} | idx>=200差异帧={W2} | st6={st6s} | 最早放任idx={fd[:5]}")
if __name__=="__main__": main()
