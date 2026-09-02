#!/usr/bin/env python3
"""replay_b_sum.py — 63/65全段 st6事件摘要（跳变类型 2→6 / 3→6）+ 事件窗口 OP128 对比"""
import glob, os, sys
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

def scan(route):
    segs=sorted({os.path.basename(os.path.dirname(p)).split('--')[-1]
                 for p in glob.glob(f"{BASE}/{route}--*--*/rlog.zst")}, key=lambda x:int(x) if x.isdigit() else 99)
    print(f"===== {route} ({len(segs)}段) =====")
    for s in segs:
        p=glob.glob(f"{BASE}/{route}--*--{s}/rlog.zst")
        if not p: continue
        stock=[]; op=[]
        for m in LogReader(p[0]):
            if m.which()!='can': continue
            for c in m.can:
                v=dec(c)
                if not v: continue
                if c.src==2: stock.append(v)
                elif c.src in (0,128): op.append(v)
        s6=[i for i,dd in enumerate(stock) if dd['st']==6]
        if not s6: 
            print(f"  seg{s:>2}: 无st6 | OP帧={len(op)}"); continue
        # 分组
        groups=[]
        for i in s6:
            if groups and i-groups[-1][-1]<=3: groups[-1].append(i)
            else: groups.append([i])
        kinds=[]
        for g in groups:
            pre = stock[g[0]-1]['st'] if g[0]>0 else '?'
            post = stock[g[-1]+1]['st'] if g[-1]+1<len(stock) else '?'
            kinds.append(f"{pre}→6→{post}")
        print(f"  seg{s:>2}: st6 {len(s6)}帧/{len(groups)}事件 跳变[{','.join(kinds[:6])}] | OP帧={len(op)}")
        # 激活中事件（pre==3）详情
        for g,k in zip(groups,kinds):
            if k.startswith('3→6') or k.startswith('4→6'):
                i0=max(0,g[0]-6); i1=min(len(stock),g[-1]+3)
                print(f"    ★激活中st6 事件@帧{g[0]}（{i0}..{i1}）——同时刻OP:")
                for j in range(i0,i1):
                    d=stock[j]; m=f"      STOCK[{j}] st={int(d['st'])} axg={d['axg']:+.2f} verz={d['verz']:+.1f} mom={int(d['mom'])} fv={int(d['fv'])} fm={int(d['fm'])} anh={int(d['anh'])}"
                    if j in s6: m+=" <<<"
                    print(m)
                # OP 在时间窗内的帧（按出现顺序近似对齐：OP和stock交替出现，用全局序号）
                print("      （OP帧近邻:）")
                # 重新扫该段拿OP带序号
                oi=0; op_near=[]
                for m in LogReader(p[0]):
                    if m.which()!='can': continue
                    for c in m.can:
                        v=dec(c)
                        if not v: continue
                        if c.src==2:
                            if len(stock) and oi not in range(i0,i1):
                                pass
                        elif c.src in (0,128):
                            if len(op) and len(stock) and abs(oi-i0)<10: pass
                    oi+=1
                break  # 每段只深挖1个激活中事件

for r in ["00000063","00000065"]:
    scan(r)
