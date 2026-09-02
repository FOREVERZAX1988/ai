#!/usr/bin/env python3
"""replay_b_align2.py — 65 seg11/15 st6窗口 OP128 vs 原厂 + gasPressed/刹车对齐"""
import glob, sys
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

BASE = "/data/media/0/realdata"
B = {'st':(57,3,False,1,0),'verz':(32,11,True,0.005,-7.22),'axg':(48,9,True,0.024,-2.016),
     'mom':(16,10,False,1,0),'fv':(13,1,False,1,0),'fm':(12,1,False,1,0),'anh':(62,1,False,1,0)}
def gs(d,sl,ln,sg,sc,of):
    v=0
    for i in range(ln):
        b=(sl+i)//8; bt=(sl+i)%8
        if d[b]&(1<<bt): v|=1<<i
    if sg and v&(1<<(ln-1)): v-=(1<<ln)
    return int(round(v*sc+of,6))
def dec(c):
    if c.address!=269 or len(c.dat)<8: return None
    dd=bytes(c.dat); return {k:gs(dd,*B[k]) for k in B}

def window(route, seg, target_idx, w=8):
    p=glob.glob(f"{BASE}/{route}--*--{seg}/rlog.zst")[0]
    frames=[]; gas=[]; brk=[]; i=0
    for m in LogReader(p):
        ww=m.which()
        if ww=='carState':
            cs=m.carState
            gas.append((i, bool(getattr(cs,'gasPressed',False)), float(getattr(cs,'gas',0)), bool(getattr(cs,'brakePressed',False))))
        elif ww=='can':
            for c in m.can:
                v=dec(c)
                if v: frames.append((i,c.src,v)); i+=1
    stock_g=[j for j,(_,s,_) in enumerate(frames) if s==2]
    g0=stock_g[target_idx]-6*3; g1=stock_g[target_idx]+22*3
    # 每30帧打印一次gas状态（carState ~100Hz, can帧密得多）
    print(f"  ★ {route}-seg{seg} st6事件@stock#{target_idx}:")
    prev_op=None
    gas_i=0
    for gi,s,v in frames:
        if gi<g0 or gi>g1: continue
        if s==2:
            mark=" <<<st6" if v['st']==6 else ""
            print(f"    STOCK st={int(v['st'])} axg={v['axg']:+.2f} verz={v['verz']:+.1f} mom={int(v['mom'])} fv={int(v['fv'])} fm={int(v['fm'])} anh={int(v['anh'])}{mark}")
        elif s in (0,128):
            st=int(v['st'])
            chg=f"  (st {prev_op}→{st})" if prev_op is not None and st!=prev_op else ""
            print(f"    OP128  st={st} axg={v['axg']:+.2f} verz={v['verz']:+.1f} mom={int(v['mom'])} fv={int(v['fv'])} fm={int(v['fm'])} anh={int(v['anh'])}{chg}")
            prev_op=st
    # gas 概要：窗口内 gas/brake 状态变化
    gw=[g for g in gas if g0<=g[0]<=g1]
    if gw:
        states=[]
        for t,gg,ga,bb in gw:
            key=f"gas={int(gg)}({ga:.0%})" if gg else ("gas=0" if not bb else "brake")
            if not states or states[-1][1]!=key: states.append((t,key))
        print("    gas/brake:", " → ".join(s[1] for s in states[-6:]))

for seg,idx in [("11",2381),("15",997)]:
    window("00000065", seg, idx)
