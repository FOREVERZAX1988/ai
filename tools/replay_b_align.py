#!/usr/bin/env python3
"""replay_b_align.py — 65激活中st6事件：OP128 vs 原厂src2 逐帧对齐对比
用全局CAN序号对齐。检测st6窗口内 OP 是否仍发 st=3/4（矛盾窗口）。
"""
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
    frames=[]  # (全局i, src, dict)
    i=0; stock_cnt=0
    for m in LogReader(p):
        if m.which()!='can': continue
        for c in m.can:
            v=dec(c)
            if not v: continue
            frames.append((i,c.src,v))
            i+=1
            if c.src==2: stock_cnt+=1
    # 找stock列表内target_idx对应的全局序号
    stock_g=[j for j,(_,s,_) in enumerate(frames) if s==2]
    g0=stock_g[target_idx]-w*3; g1=stock_g[target_idx]+20*3+6
    print(f"  ★ {route}-seg{seg} st6事件@stock#{target_idx} 全局帧{g0}..{g1}:")
    prev_op_st=None
    for j,(gi,s,v) in enumerate(frames):
        if gi<g0 or gi>g1: continue
        if s==2:
            m=f"    STOCK st={int(v['st'])} axg={v['axg']:+.2f} verz={v['verz']:+.1f} mom={int(v['mom'])} fv={int(v['fv'])} fm={int(v['fm'])} anh={int(v['anh'])}"
            if v['st']==6: m+=" <<<st6"
            print(m)
        elif s in (0,128):
            opv=f"    OP128  st={int(v['st'])} axg={v['axg']:+.2f} verz={v['verz']:+.1f} mom={int(v['mom'])} fv={int(v['fv'])} fm={int(v['fm'])} anh={int(v['anh'])}"
            if prev_op_st is not None and int(v['st'])!=prev_op_st: opv+=f"  (st {prev_op_st}→{int(v['st'])})"
            if int(v['st']) in (3,4) and prev_op_st is not None: pass
            prev_op_st=int(v['st'])
            print(opv)

for seg,idx in [("5",1298),("11",2381),("15",997)]:
    window("00000065", seg, idx)
