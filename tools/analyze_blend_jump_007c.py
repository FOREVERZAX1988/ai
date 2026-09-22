#!/usr/bin/env python3
"""复现 radard A2 混合后的最终 dRel, 量化用户可见跳动来源
最终 dRel = (1-w_vis)*d_stock + w_vis*d_vis
跳动来源: dS_after=|Δd_stock|, dV_after=|Δd_vis|, dF_after=|Δd_final|
判定一个"用户可见大跳"(>2m/frame)主要由谁造成: 比较 dS_after 与 dV_after
同时统计: 源切换(idx 0/1021 -> 有效, 混补变纯视觉/纯原厂)帧
"""
import glob, sys, bisect
sys.path.insert(0,'/data/openpilot')
from openpilot.tools.lib.logreader import LogReader
TA,TB=0.008969,0.332
REL_TH=0.3
BASE='/data/media/0/realdata'; PREFIX='0000007c'
SEGS=[4,6,8,12,5,10]
def t_from_idx(i): return TA*i+TB
def d_from_idx(i,v): return t_from_idx(i)*max(v,5.0)
def blend(d_stock,d_vis):
    if d_stock<=0 or d_vis<=0: return d_stock if d_stock>0 else d_vis
    rel=abs(d_vis-d_stock)/max(d_stock,1.0)
    w=min(0.7+(rel/REL_TH)*0.3,1.0)
    df = d_stock if d_stock<15 else (40.0 if d_stock<40 else (60.0 if d_stock<60 else 200.0))
    if df<15: f=0.5
    elif df<40: f=1.17
    elif df<60: f=1.0
    else: f=0.83
    w_vis=min((1.0-w)*f,0.5)
    return (1.0-w_vis)*d_stock+w_vis*d_vis
def scan(segfile):
    cur_idx=0.0;cur_v=0.0;idx_t={};vis=[]
    for m in LogReader(segfile):
        w=m.which()
        if w=='can':
            for c in m.can:
                if c.src==2 and c.address==780 and len(c.dat)>=7:
                    cur_idx=float((c.dat[3]|(c.dat[4]<<8))&0x3FF)
        elif w=='carState': cur_v=float(m.carState.vEgo)
        elif w=='modelV2':
            idx_t[m.logMonoTime]=(cur_idx,cur_v)
            ld=m.modelV2.leadsV3
            if len(ld)>0 and len(ld[0].x)>0: vis.append((m.logMonoTime,float(ld[0].x[0]),float(ld[0].prob)))
    times=sorted(idx_t); rows=[]
    for mt,vd,p in vis:
        j=bisect.bisect_right(times,mt)-1
        if j<0: continue
        idx,v=idx_t[times[j]]
        ds=d_from_idx(idx,v); dfin=blend(ds,vd); valid=0<idx<1021
        rows.append((mt,idx,v,ds,vd,dfin,valid))
    rows.sort(); return rows
def classify(rows):
    c={'idx':0,'vis':0,'both':0,'switch':0,'big_switch':0,'big_noswitch':0}
    ex={}
    for i in range(1,len(rows)):
        a=rows[i-1]; b=rows[i]
        dS=abs(b[3]-a[3]); dV=abs(b[4]-a[4]); dF=abs(b[5]-a[5])
        if dF<2.0: continue
        va=a[6]; vb=b[6]
        if va!=vb:
            c['switch']+=1
            if dF>5.0: c['big_switch']+=1
            ex.setdefault('switch',[]).append(f"t={b[0]/1e9:.1f}s v={b[2]:.0f} idx={a[1]:.0f}->{b[1]:.0f} dF={dF:.1f} ds={a[3]:.0f}->{b[3]:.0f} dv={a[4]:.0f}->{b[4]:.0f}")
            continue
        c['big_noswitch']+=1
        if dS>dV: k='idx'
        elif dV>dS: k='vis'
        else: k='both'
        c[k]+=1
        if len(ex.setdefault(k,[]))<5: ex[k].append(f"t={b[0]/1e9:.1f}s idx={a[1]:.0f}->{b[1]:.0f} dF={dF:.1f} ds={a[3]:.0f}->{b[3]:.0f} dv={a[4]:.0f}->{b[4]:.0f} v={b[2]:.0f}")
    return c,ex
def main():
    rows=[]
    for seg in SEGS:
        for f in sorted(glob.glob(f'{BASE}/{PREFIX}--*--{seg}/rlog.zst')): rows+=scan(f)
    rows.sort(key=lambda r:r[0])
    c,ex=classify(rows)
    print(f"总帧 {len(rows)} | 用户可见大跳(dF>2m/frame):\n")
    print(f"  源切换(混补变纯): {c['switch']}  (其中>5m: {c['big_switch']})")
    print(f"  无切换  idx主导: {c['idx']}")
    print(f"  无切换  vis主导: {c['vis']}")
    print(f"  无切换  双因   : {c['both']}")
    print(f"  无切换  合计   : {c['big_noswitch']}")
    print("\n=== 样例: 源切换 ===")
    for s in ex.get('switch',[])[:8]: print("  "+s)
    print("\n=== 样例: idx主导(无切换) ===")
    for s in ex.get('idx',[])[:8]: print("  "+s)
    print("\n=== 样例: vis主导(无切换) ===")
    for s in ex.get('vis',[])[:8]: print("  "+s)
main()
