#!/usr/bin/env python3
"""007c 逐帧对齐: 原厂idx反推d_stock vs 视觉lead dRel, 量化跳动来源
跳动来源判定（相邻帧 dt≈0.1s, 车速v已知）:
  - dS_jump = |Δd_stock| : 原厂idx引起的距离变化
  - dV_jump = |Δd_vis  | : 视觉lead引起的距离变化
  - idx_spike: |Δidx|>某阈值 且 下一帧跳回 → 尖峰抖动
  d_stock = MACAN_B1_T_A*idx + B,  *max(v,5) —— 与 radard A2 同口径
用法: python3 ai/tools/analyze_idx_jitter_007c.py
"""
import glob, sys, os
sys.path.insert(0,'/data/openpilot')
from openpilot.tools.lib.logreader import LogReader

TA, TB = 0.008969, 0.332
BASE='/data/media/0/realdata'
PREFIX='0000007c'
SEGS=[4,6,8,12,5,10]  # 4/6/8 停车抖动样本, 5/10/12 驾驶/切换样本

def t_from_idx(idx): return TA*idx+TB
def d_from_idx(idx,v): return t_from_idx(idx)*max(v,5.0)

def scan(segfile):
    """返回 (idx时序, v_ego时序, vis_d时序, prob时序) 每帧对齐(以modelV2节拍)"""
    cur_idx=0.0; cur_v=0.0
    # 以 logMonoTime 键控
    idx_t={}; vis=[]
    for m in LogReader(segfile):
        w=m.which()
        if w=='can':
            for c in m.can:
                if c.src==2 and c.address==780 and len(c.dat)>=7:
                    cur_idx=float((c.dat[3]|(c.dat[4]<<8))&0x3FF)
        elif w=='carState':
            cur_v=float(m.carState.vEgo)
        elif w=='modelV2':
            mt=m.logMonoTime
            idx_t[mt]=(cur_idx,cur_v)
            ld=m.modelV2.leadsV3
            if len(ld)>0 and len(ld[0].x)>0:
                vis.append((mt,float(ld[0].x[0]),float(ld[0].prob)))
    # 对齐: 对每个modelV2帧找最近的前向can idx
    import bisect
    times=sorted(idx_t.keys())
    rows=[]
    for mt,vd,prob in vis:
        j=bisect.bisect_right(times,mt)-1
        if j<0: continue
        idx,v=idx_t[times[j]]
        rows.append((mt,idx,v,vd,prob))
    rows.sort()
    return rows

def analyze(rows):
    # 跳动统计
    jumps_src={'idx':0,'vis':0,'both':0,'small':0}
    idx_spike=0; idx_spike_amp=[]
    big_jump_log=[]
    n_switch=0
    for i in range(1,len(rows)):
        _,i0,v0,v0d,p0=rows[i-1]
        _,i1,v1,v1d,p1=rows[i]
        ds0=d_from_idx(i0,v0); ds1=d_from_idx(i1,v1)
        dS=abs(ds1-ds0); dV=abs(v1d-v0d)
        if ds0==0 or ds1==0: continue
        # 源切换检测: 一个靠视觉一个靠原厂
        if (i0<=0 or i0>=1021) and (0<i1<1021): n_switch+=1; continue
        if (i1<=0 or i1>=1021) and (0<i0<1021): n_switch+=1; continue
        big = dS>2.0 or dV>2.0
        if not big: jumps_src['small']+=1; continue
        if dS>2.0 and dV>2.0: jumps_src['both']+=1
        elif dS>dV: jumps_src['idx']+=1
        else: jumps_src['vis']+=1
        # idx 尖峰: 大步进且下一帧跳回
        if dS>2.0 and i+1<len(rows):
            _,i2,v2,_,_=rows[i+1]
            dsn=d_from_idx(i2,v1)
            if abs(d_from_idx(i2,v2)-ds1)<1.5:  # 回弹
                idx_spike+=1; idx_spike_amp.append(dS)
        if len(big_jump_log)<8 and dS>2.0:
            big_jump_log.append(f"t={rows[i][0]/1e9:.1f}s idx {i0:.0f}->{i1:.0f} dS {dS:.1f}m dV {dV:.1f}m v {v1:.1f}")
    return jumps_src,idx_spike,idx_spike_amp,big_jump_log,n_switch,len(rows)

def main():
    print(f"{'seg':>4} {'帧数':>6} {'小跳':>5} {'idx主导':>7} {'vis主导':>7} {'双因':>5} {'源切换':>5} {'idx尖峰':>7}  大跳样例")
    agg={'small':0,'idx':0,'vis':0,'both':0}; total_n=0; total_switch=0; total_spike=0
    for seg in SEGS:
        files=sorted(glob.glob(f'{BASE}/{PREFIX}--*--{seg}/rlog.zst'))
        if not files: 
            print(f"{seg:>4} 无文件"); continue
        rows=[]
        for f in files: rows+=scan(f)
        rows.sort(key=lambda r:r[0])
        js,spk,spk_amp,big,nsw,n=analyze(rows)
        for k in agg: agg[k]+=js[k]
        total_n+=n; total_switch+=nsw; total_spike+=spk
        print(f"{seg:>4} {n:>6} {js['small']:>5} {js['idx']:>7} {js['vis']:>7} {js['both']:>5} {nsw:>5} {spk:>7}  {'; '.join(big)[:70]}")
    tot=sum(agg.values())
    print(f"\n汇总: 帧{total_n} 小跳{agg['small']} idx主导{agg['idx']} vis主导{agg['vis']} 双因{agg['both']} 源切换{total_switch} idx尖峰{total_spike}")
    print(f"idx主导占比(大跳中): {agg['idx']/max(agg['idx']+agg['vis']+agg['both'],1):.0%}")

main()
