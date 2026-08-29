#!/usr/bin/env python3
"""scan_st6_all.py — st6事件全量扫描+根因分类+补丁覆盖判定
扫 route 全部段: bus2(原厂) st==6 上升沿事件
对每个事件: bus2 vs bus128(OP代发) ±15帧完整对比, 自动分类根因, 判定补丁覆盖
用法: python3 scan_st6_all.py ROUTE [ROUTE...]
"""
import sys, glob, os, re
sys.path.insert(0,"/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
from collections import deque
from multiprocessing import Pool
BASE="/data/media/0/realdata"
DBC="/data/openpilot/opendbc_repo/opendbc/dbc/vw_mlb.dbc"
def sigs():
    L=open(DBC,encoding="latin-1").read().splitlines()
    s=next(i for i,l in enumerate(L) if l.startswith('BO_ 269 '))
    e=next(i for i in range(s+1,len(L)) if L[i].startswith('BO_ '))
    out={}
    for l in "\n".join(L[s:e]).splitlines():
        m=re.match(r'^\s*SG_ (\w+) : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)',l)
        if m: out[m.group(1)]=(int(m.group(2)),int(m.group(3)),m.group(5)=='-',float(m.group(6)),float(m.group(7)))
    return out
def gs(d,sl,ln,sg,sc=1.0,of=0.0):
    if len(d)<=(sl+ln-1)//8: return 0
    v=0
    for i in range(ln):
        b=(sl+i)//8; bt=(sl+i)%8
        if d[b]&(1<<bt): v|=(1<<i)
    if sg and v&(1<<(ln-1)): v-=(1<<ln)
    return v*sc+of
S=sigs()
SIG={'st':S['ACC_Status_ACC'],'verz':S['ACC_Verz_anf'],'mom':S['ACC_Momentenanforderung'],
     'axg':S['ACC_ax_Getriebe'],'loes':S['ACC_Loeseanforderung'],'fv':S['ACC_Freigabe_Verzanf'],
     'fm':S['ACC_Freigabe_Momentenanf'],'anh':S['ACC_Anhalten'],'esp':S['ACC_Beeinflussung_ESP']}
def dec(dat):
    return {k:gs(dat,*v) for k,v in SIG.items()}
def classify(b2,b1):
    """b2=bus2原厂st6前一帧(st!=6), b1=bus128最后一帧; 返回(根因, 补丁覆盖?)"""
    if b2 is None: return ("无bus2数据", "?")
    if b1 is None: return ("无OP代发(纯原厂/自检)", "不适用")
    # 用st6前一帧的原厂值判定（st6帧本身是故障清零态，不可用于分类）
    if b2['verz'] < -0.5 and b1['verz'] > -0.05:
        return ("verz矛盾(OP0vs原厂负)", "MacanVerzFollow✅")
    if b2['axg'] > 0.14 and b1['axg'] < 0.1:
        return ("axG不足(SnG起步)", "MacanAxGComp✅")
    if b2['mom'] < 60 and b1['mom'] >= 60:
        return ("mom矛盾(OP发力vs原厂撤力)", "stock_follow✅")
    if b1['loes']>=1 and (b1['verz'] < -0.05 or b1['anh']>=1):
        return ("loes矛盾(loes+刹车共存)", "已事件化修复✅")
    if b2['anh']>=1 and b1['anh']<1:
        return ("anh矛盾(OP未保持停车)", "stopping_hold✅")
    if b1['esp']>=1 and b2['esp']<1:
        return ("ESP矛盾(OP请求vs原厂不请求)", "透传stock_esp✅")
    return ("其他/未分类", "⚠️需人工确认")
def scan_seg(arg):
    route,seg=arg
    p=glob.glob(f"{BASE}/{route}--*--{seg}/rlog.zst")
    if not p: return None
    hist2=deque(maxlen=16); hist1=deque(maxlen=16); prev=-1; events=[]
    try:
        for m in LogReader(p[0]):
            if m.which()!='can': continue
            for c in m.can:
                if c.address!=269: continue
                d=bytes(c.dat)
                if len(d)<8: continue
                r=dec(d)
                if c.src==2:
                    hist2.append(r)
                    if r['st']==6 and prev!=6:
                        # b2=st6前一帧(st!=6) —— st6帧本身是故障清零态
                        b2=None
                        for f in reversed(list(hist2)):
                            if f['st']!=6:
                                b2=f; break
                        b1=list(hist1)[-1] if hist1 else None
                        events.append((int(seg), int(prev), b2, b1))
                    prev=r['st']
                elif c.src==128:
                    hist1.append(r)
    except Exception as ex:
        return (seg, f"读取失败:{type(ex).__name__}")
    return (seg, events)
def main():
    routes=sys.argv[1:]
    if not routes: print("用法: scan_st6_all.py ROUTE [ROUTE...]"); return
    for route in routes:
        segs=[os.path.basename(os.path.dirname(p)).split('--')[-1] for p in sorted(glob.glob(f"{BASE}/{route}--*--*/rlog.zst"))]
        print(f"\n===== {route} ({len(segs)}段) st6事件 =====", flush=True)
        with Pool(4) as pool:
            res=pool.map(scan_seg,[(route,s) for s in segs])
        total=0; cats={}
        for seg,ev in res:
            if isinstance(ev,str): print(f"  seg{seg}: {ev}"); continue
            if not ev: continue
            for (s,prev,b2,b1) in ev:
                cause,cover=classify(b2,b1)
                total+=1
                cats.setdefault(cause,[]).append((s,prev,b2,b1))
        if total==0:
            print(f"  ✅ 无 st6 事件")
            continue
        print(f"  共 {total} 个 st6 事件:")
        for cause,items in sorted(cats.items(), key=lambda x:-len(x[1])):
            cover=classify(items[0][2],items[0][3])[1]
            print(f"\n  [{cause}] x{len(items)}  判定: {cover}")
            for (s,prev,b2,b1) in items[:8]:
                v2=f"st{int(b2['st'])} vz={b2['verz']:+.2f} mom={b2['mom']:.0f} axg={b2['axg']:+.2f} loes={int(b2['loes'])} anh={int(b2['anh'])} esp={int(b2['esp'])}"
                v1=f"st{int(b1['st'])} vz={b1['verz']:+.2f} mom={b1['mom']:.0f} axg={b1['axg']:+.2f} loes={int(b1['loes'])} anh={int(b1['anh'])} esp={int(b1['esp'])}" if b1 else "无OP帧"
                print(f"    seg{s:>3} prev_st={prev}: 原厂[{v2}] | OP[{v1}]")
if __name__=="__main__": main()
