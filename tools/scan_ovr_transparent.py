#!/usr/bin/env python3
"""scan_ovr_transparent.py — 超驰(st=4)窗口: 当前OP帧vs原厂帧差值 + 模拟透传后残余差值
验证: 超驰时透传原厂verz/axG 能否消除执行矛盾(差值>0.3的帧)
用法: python3 scan_ovr_transparent.py ROUTE [ROUTE...]
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
    svz=saxg=None; ovz=oaxg=None
    in_ovr=False; w_start=None; w_dur=0
    wins=[]  # (start_s, dur_s, n_op, dv_cur, da_cur, dv_tt, da_tt, clip)
    cur=None
    t0=None
    for m in LogReader(sp):
        if m.which()!='can': continue
        for c in m.can:
            if len(c.dat)<8: continue
            d=bytes(c.dat)
            if c.address==269:
                st=int(gs(d,57,3)); vz=round(gs(d,32,11,0.005,-7.22),2); axg=round(gs(d,48,9,0.024,-2.016),2)
                if c.src==2:
                    svz,saxg=vz,axg
                    if t0 is None: t0=m.logMonoTime
                    if st==4 and not in_ovr:
                        in_ovr=True; w_start=m.logMonoTime; w_dur=0
                        cur=[w_start,0,0,0,0,0,0,0]
                    elif st!=4 and in_ovr:
                        in_ovr=False; cur[1]=w_dur; wins.append(cur); cur=None
                    if in_ovr: w_dur=m.logMonoTime-w_start
                elif c.src==128:
                    ovz,oaxg=vz,axg
                    if in_ovr and svz is not None and cur is not None:
                        cur[2]+=1
                        dv=abs(ovz-svz); da=abs(oaxg-saxg)
                        if dv>0.3: cur[3]+=1
                        if da>0.3: cur[4]+=1
                        # 模拟透传: verz=clip(svz,-2.2,1.0), axg=saxg(原样)
                        # 透传后矛盾=透传值与原厂值之差(verz仅钳制引入, axG恒0)
                        tvz=max(min(svz,1.0),-2.2)
                        if abs(tvz-svz)>0.3: cur[5]+=1; cur[7]+=1
                        # cur[6] 恒0 (axG原样透传=原厂值)
    if in_ovr and cur is not None:
        cur[1]=w_dur; wins.append(cur)
    return seg, wins
def main():
    routes=sys.argv[1:]
    if not routes: print("用法: scan_ovr_transparent.py ROUTE [ROUTE...]"); return
    for route in routes:
        segs=sorted(glob.glob(f"{BASE}/{route}--*--*/rlog.zst"))
        with Pool(4) as pool:
            res=pool.map(scan_seg,[(route,sp) for sp in segs])
        tot=[0,0,0,0,0]; nwin=0
        print(f"\n===== {route} 超驰窗口透传验证 (差值阈值0.3) =====")
        print("  窗口: 时长 | OP帧 | 当前verz矛盾 | 当前axG矛盾 | 透传后verz矛盾 | 透传后axG矛盾(恒0) | verz钳制帧")
        for seg,wins in res:
            for w in wins:
                nwin+=1
                print(f"  {seg}: {w[1]/1e9:.1f}s | {w[2]} | {w[3]} | {w[4]} | {w[5]} | {w[6]} | {w[7]}")
                tot[0]+=w[2]; tot[1]+=w[3]; tot[2]+=w[4]; tot[3]+=w[5]; tot[4]+=w[6]
        print(f"  合计{nwin}窗口 {tot[0]}OP帧: 当前矛盾 verz={tot[1]}({tot[1]*100//max(tot[0],1)}%) axG={tot[2]}({tot[2]*100//max(tot[0],1)}%) || 透传后矛盾 verz={tot[3]} axG={tot[4]}")
if __name__=="__main__": main()
