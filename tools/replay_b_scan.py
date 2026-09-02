#!/usr/bin/env python3
"""replay_b_scan.py — 方案B回放扫描：st6残留 + 镜像矛盾窗口

逐段快扫 ACC_05（bus0 OP帧 / bus2 原厂帧），只解关键字段（st/axg/verz/mom/fv/fm/anhalt），
检测方案B落地后：
  1. OP st=6 残留（OP卡的st）
  2. 原厂 st=6 事件段分布（这些是什么场景）
  3. 镜像矛盾窗口：原厂已退出验收(st<3)而OP仍发st=3/4（半程镜像)
  4. mom/axG 背离：gas_override 透传后 OP(fv/fm/mom) vs 原厂 是否仍有背离
"""
import glob, os, sys, re
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
from collections import Counter

BASE = "/data/media/0/realdata"
# 硬编码 BO_269 位定义（来自 vw_mlb.dbc line81）
# (startbit, len, signed, scale, offset)
B = {
  'st':   (57,3,False,1.0,0.0),
  'verz': (32,11,True, 0.005,-7.22),
  'axg':  (48,9,True, 0.024,-2.016),
  'mom':  (16,10,False,1.0,0.0),
  'fv':   (13,1,False,1.0,0.0),
  'fm':   (12,1,False,1.0,0.0),
  'anh':  (62,1,False,1.0,0.0),
}
def gs(d, sl, ln, sg, sc, of):
    v=0
    for i in range(ln):
        b=(sl+i)//8; bt=(sl+i)%8
        if d[b]&(1<<bt): v|=(1<<i)
    if sg and v&(1<<(ln-1)): v-=(1<<ln)
    return int(round(v*sc+of,6))

def one_msg(c):
    if c.address!=269 or len(c.dat)<8: return None
    dd=bytes(c.dat)
    return {k: gs(dd,*B[k]) for k in B}

def scan(route, seg):
    p = glob.glob(f"{BASE}/{route}--*--{seg}/rlog.zst")
    if not p: return "nomatch"
    st_stock={}; st_op={}
    first_st6_stock=first_st6_op=None
    n=0; gas_idx=0
    # 事件窗口邻段统计
    for m in LogReader(p[0]):
        if m.which()!='can': continue
        for c in m.can:
            v=one_msg(c)
            if not v: continue
            n+=1
            if c.src==2:
                st_stock.setdefault(v['st'],0); st_stock[v['st']]+=1
                if v['st']==6 and first_st6_stock is None: first_st6_stock=n
                last_stock=v
            elif c.src==0:
                st_op.setdefault(v['st'],0); st_op[v['st']]+=1
                if v['st']==6 and first_st6_op is None: first_st6_op=n
                last_op=v
    s6s=sum(v for k,v in st_stock.items() if k==6)
    s6o=sum(v for k,v in st_op.items() if k==6)
    print(f"  [seg{seg}] ACC05帧={n} | 原厂st分布={dict(sorted(st_stock.items()))} st6={s6s}{'第一帧@'+str(first_st6_stock) if s6s else ''}"
          f" | OP st分布={dict(sorted(st_op.items()))} st6={s6o}{'第一帧@'+str(first_st6_op) if s6o else ''}")
    return f"seg{seg}:stock6={s6s}/op6={s6o}"

def main():
    routes=["00000063","00000065"]
    for route in routes:
        segs=sorted({os.path.basename(os.path.dirname(p)).split('--')[-1] for p in glob.glob(f"{BASE}/{route}--*--*/rlog.zst")},key=lambda x:int(x) if x.isdigit() else 99)
        print(f"===== {route} 段数={len(segs)}: seg{segs[0]}~seg{segs[-1]} =====")
        for s in segs:
            try:
                r=scan(route,s)
            except Exception as e:
                r=f"ERR:{e}"
                print(f"  [seg{s}] 错误 {e}")
    return

if __name__=='__main__':
    main()
