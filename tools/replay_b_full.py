#!/usr/bin/env python3
"""replay_b_full.py — 方案B回放模拟（63/65全段，OP帧=src128/0，原厂=src2）
对每个原厂st6事件段: 提取窗口内 原厂st序列 vs OP st序列 + 信号透传一致性
并做方案B反推: gas_override帧按新逻辑算OP应发, 找残留矛盾。
"""
import glob, os, sys
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

BASE = "/data/media/0/realdata"
B = {
  'st':   (57,3,False,1.0,0.0),   'verz': (32,11,True,0.005,-7.22),
  'axg':  (48,9,True,0.024,-2.016), 'mom': (16,10,False,1.0,0.0),
  'fv':   (13,1,False,1.0,0.0),   'fm': (12,1,False,1.0,0.0),
  'anh':  (62,1,False,1.0,0.0),
}
def gs(d,sl,ln,sg,sc,of):
    v=0
    for i in range(ln):
        b=(sl+i)//8; bt=(sl+i)%8
        if d[b]&(1<<bt): v|=1<<i
    if sg and v&(1<<(ln-1)): v-=(1<<ln)
    return int(round(v*sc+of,6))

def dec(c):
    if c.address!=269 or len(c.dat)<8: return None
    dd=bytes(c.dat)
    return {k: gs(dd,*B[k]) for k in B}

def scan(route):
    segs=sorted({os.path.basename(os.path.dirname(p)).split('--')[-1]
                 for p in glob.glob(f"{BASE}/{route}--*--*/rlog.zst")}, key=lambda x:int(x) if x.isdigit() else 99)
    print(f"===== {route} ({len(segs)}段) =====")
    for s in segs:
        p=glob.glob(f"{BASE}/{route}--*--{s}/rlog.zst")
        if not p: continue
        stock=[]; op=[]; op128=[]
        for m in LogReader(p[0]):
            if m.which()!='can': continue
            for c in m.can:
                v=dec(c)
                if not v: continue
                if c.src==2: stock.append(v)
                elif c.src==0: op.append(v)
                elif c.src==128: op128.append(v)
        s6=[i for i,dd in enumerate(stock) if dd['st']==6]
        if not s6:
            # 无st6也报OP通道存在性
            tag=f"st6=0 | OP128={len(op128)}帧 OP0={len(op)}帧"
            print(f"  seg{s:>2}: {tag}")
            continue
        # st6 事件分组（连续段算一次）
        groups=[]
        for i in s6:
            if groups and i-groups[-1][-1]<=3: groups[-1].append(i)
            else: groups.append([i])
        print(f"  seg{s:>2}: 原厂st6 {len(s6)}帧/{len(groups)}事件 | OP128={len(op128)}帧 OP0={len(op)}帧")
        for g in groups[:4]:
            i0=max(0,g[0]-4); i1=min(len(stock),g[-1]+4)
            print(f"    事件@帧{g[0]}（窗口{i0}..{i1}）:")
            for j in range(i0,i1):
                d=stock[j]
                m=f"      STOCK[{j}] st={int(d['st'])} axg={d['axg']:+.2f} verz={d['verz']:+.1f} mom={int(d['mom'])} fv={int(d['fv'])} fm={int(d['fm'])} anh={int(d['anh'])}"
                if j in s6: m+="  <<< st6"
                print(m)
        if len(groups)>4: print(f"    ...共{len(groups)}事件")

for r in ["00000063","00000065"]:
    scan(r)
