#!/usr/bin/env python3
"""落点1 007c回放: 分类 dF>5m 大跳的真实来源 (2026-09-22)
对大跳帧按其 idx 状态分类:
  - inv_inv  : 该帧 idx 无效(0/1021)且此前也无效->滞回无法救(超窗/无有效base)
  - inv_sht  : 该帧 idx 无效但窗口内有有效idx-> 滞回应能救
  - valid_jump: 该帧 idx 有效域内大幅跳变(非0/1021边界)-> 落点1不覆盖
  - vis_dom  : 该帧由视觉主导(dVis>dS)
"""
import glob, sys, bisect
sys.path.insert(0,'/data/openpilot')
from openpilot.tools.lib.logreader import LogReader
TA,TB=0.008969,0.332
REL_TH=0.3
HYST_WIN=0.6
BASE='/data/media/0/realdata'; PREFIX='0000007c'
SEGS=[4,6,8,12,5,10]
def t_from_idx(i): return TA*i+TB
def d_from_idx(i,v): return t_from_idx(i)*max(v,5.0)
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
            if len(ld)>0 and len(ld[0].x)>0: vis.append((m.logMonoTime,float(ld[0].x[0])))
    times=sorted(idx_t); rows=[]
    for mt,vd in vis:
        j=bisect.bisect_right(times,mt)-1
        if j<0: continue
        idx,v=idx_t[times[j]]
        rows.append((mt,idx,v,vd))
    rows.sort(); return rows

def classify_bigjumps(rows):
    """遍历帧, 统计 dF>5m 大跳来源分类(基于原始idx+dvis)"""
    stat={'inv_inv':0,'inv_sht':0,'valid_jump':0,'vis_dom':0}
    last_idx=0.0; last_t=0.0
    for i in range(1,len(rows)):
        (t0,i0,v0,dv0)=rows[i-1]; (t1,i1,v1,dv1)=rows[i]
        ds0=d_from_idx(i0,v0); ds1=d_from_idx(i1,v1)
        dS=abs(ds1-ds0); dV=abs(dv1-dv0)
        if max(dS,dV)<5.0: continue
        # 判定: 视觉主导?
        if dV>=dS and dS<2.0:
            stat['vis_dom']+=1; continue
        # idx 主导 -> 看是否无效域
        inv0=not(0<i0<1021); inv1=not(0<i1<1021)
        if inv1:
            # 该帧无效, 窗口内是否有有效 idx?
            if 0<last_idx<1021 and (t1-last_t)<=HYST_WIN*1e9:
                stat['inv_sht']+=1   # 滞回应能救
            else:
                stat['inv_inv']+=1   # 滞回救不了(无有效base/超窗)
        elif inv0:
            stat['inv_sht']+=1
        else:
            stat['valid_jump']+=1    # 有效域内大幅跳变
        if 0<i1<1021: last_idx=i1; last_t=t1
    return stat

def main():
    rows=[]
    for seg in SEGS:
        for f in sorted(glob.glob(f'{BASE}/{PREFIX}--*--{seg}/rlog.zst')): rows+=scan(f)
    rows.sort(key=lambda r:r[0])
    st=classify_bigjumps(rows)
    print(f"总帧 {len(rows)}\n")
    print("dF>5m 大跳来源分类:")
    for k,v in st.items(): print(f"  {k:10s}: {v}")
    print("\n说明:")
    print("  inv_sht   = idx 短暂无效但窗口内有有效基准 -> 落点1 滞回应消除")
    print("  inv_inv   = idx 持续无效/无有效基准          -> 落点1 救不了")
    print("  valid_jump= idx 有效域内大幅跳变              -> 落点1 不覆盖")
    print("  vis_dom   = 视觉主导大跳                     -> 落点1 不覆盖")
main()
