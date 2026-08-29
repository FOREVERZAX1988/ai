#!/usr/bin/env python3
"""scan_loes_conflict.py — 原厂SnG vs OP跟停 矛盾窗口扫描
找: bus2原厂 loes=1(雷达请求起步) 期间, bus128 OP代发帧仍 anh=1 或 verz<-1.5(停车保持)
这= "原厂检测到前车起步, OP视觉没检测到仍保持刹车" 的感知差异矛盾帧
用法: python3 scan_loes_conflict.py ROUTE [ROUTE...]
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
    loes_n=0; conflict=0; op_sync=0; samp=[]
    last_op=None
    try:
        for m in LogReader(sp):
            if m.which()!='can': continue
            for c in m.can:
                if c.address!=269 or len(c.dat)<8: continue
                d=bytes(c.dat)
                if c.src==2:
                    loes=int(gs(d,43,1))
                    if loes==1:
                        loes_n+=1
                        if last_op is not None:
                            op_anh=int(last_op[0]); op_verz=last_op[1]; op_st=int(last_op[2])
                            if op_anh==1 or op_verz < -1.5:
                                conflict+=1
                                if len(samp)<4:
                                    samp.append(f"seg{seg}: 原厂loes=1(前车起步) vs OP anh={op_anh} verz={op_verz:+.2f} st={op_st} ← 矛盾帧")
                            elif op_verz >= 0.0:
                                op_sync+=1
                elif c.src==128:
                    last_op=(gs(d,62,1), gs(d,32,11,0.005,-7.22), gs(d,57,3))
    except Exception:
        pass
    return seg, loes_n, conflict, op_sync, samp
def main():
    routes=sys.argv[1:]
    if not routes: print("用法: scan_loes_conflict.py ROUTE [ROUTE...]"); return
    for route in routes:
        segs=sorted(glob.glob(f"{BASE}/{route}--*--*/rlog.zst"))
        with Pool(4) as pool:
            res=pool.map(scan_seg,[(route,sp) for sp in segs])
        T=sum(r[1] for r in res); C=sum(r[2] for r in res); S=sum(r[3] for r in res)
        ss=[s for r in res for s in r[4]]
        print(f"\n===== {route}: 原厂loes=1总帧={T}, 期间OP同步起步(verz>=0)={S}, OP仍停车保持(矛盾)={C} =====")
        for s in ss: print("  ⚠️", s)
        if T and C==0: print(f"  ✅ 无矛盾帧 (0/{T}) — 原厂SnG期间OP从未保持刹车")
if __name__=="__main__": main()
