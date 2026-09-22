#!/usr/bin/env python3
"""落点1验证: idx失效保持(hold last-good)后, 007c 源切换台阶级跳是否消除
对比: 补丁前(直接return纯视觉) vs 补丁后(last-good hold)
输出两种口径下的 用户可见大跳(dF>2m/帧) 数量与>5m数量
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

def blend_patch(d_stock,d_vis,last_good):
    """返回(补丁后最终dRel, last_good) — 模拟 _macan_fuse_leads + 落点1 hold
    d_stock<=0(无效) 时用 last-good hold(仅尺度相容), 有效时刷新 last_good 并做 A2 blend
    """
    if d_stock<=0:  # idx 失效
        if last_good['has']:
            hd=last_good['drel']
            if d_vis>0 and hd>0:
                rel=abs(d_vis-hd)/max(hd,1.0)
                if rel<=REL_TH:
                    return hd, last_good
            return d_vis, last_good
        return d_vis, last_good
    # idx 有效: 刷新 last-good
    last_good={'has':True,'drel':max(d_stock,0.0)}
    if d_stock<=0 or d_vis<=0: return d_vis if d_vis>0 else d_stock, last_good
    rel=abs(d_vis-d_stock)/max(d_stock,1.0)
    w=min(0.7+(rel/REL_TH)*0.3,1.0)
    df = d_stock if d_stock<15 else (40.0 if d_stock<40 else (60.0 if d_stock<60 else 200.0))
    f = 0.5 if df<15 else (1.17 if df<40 else (1.0 if df<60 else 0.83))
    w_vis=min((1.0-w)*f,0.5)
    return (1.0-w_vis)*d_stock+w_vis*d_vis, last_good

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
        ds=d_from_idx(idx,v) if 0<idx<1021 else 0.0  # 0=无效
        rows.append((mt,idx,v,ds,vd))
    rows.sort(); return rows

def main():
    rows=[]
    for seg in SEGS:
        for f in sorted(glob.glob(f'{BASE}/{PREFIX}--*--{seg}/rlog.zst')): rows+=scan(f)
    rows.sort(key=lambda r:r[0])
    # 补丁前(直接 return 纯视觉) 与 补丁后(hold)
    c_before={'big':0,'big5':0,'switch':0}; c_after={'big':0,'big5':0,'switch':0}
    prev_before=None; prev_after=None; lg={'has':False,'drel':0.0}
    for (mt,idx,v,ds,vd) in rows:
        # 补丁前: idx无效=>纯视觉, 有效=>blend
        if ds<=0: db=vd
        else:
            rel=abs(vd-ds)/max(ds,1.0); w=min(0.7+(rel/REL_TH)*0.3,1.0)
            wv=min((1.0-w)*(0.5 if ds<15 else (1.17 if ds<40 else (1.0 if ds<60 else 0.83))),0.5)
            db=(1.0-wv)*ds+wv*vd
        daf,lg=blend_patch(ds,vd,lg)
        if prev_before is not None:
            dF=abs(db-prev_before)
            if dF>2.0:
                c_before['big']+=1
                if dF>5.0: c_before['big5']+=1
            dF2=abs(daf-prev_after)
            if dF2>2.0:
                c_after['big']+=1
                if dF2>5.0: c_after['big5']+=1
        prev_before=db; prev_after=daf
    print(f"总帧 {len(rows)}")
    print(f"补丁前(user可见大跳>2m): {c_before['big']}   (>5m: {c_before['big5']})")
    print(f"补丁后(idx失效hold)    : {c_after['big']}   (>5m: {c_after['big5']})")
    print(f"消除率: 大跳 {(c_before['big']-c_after['big'])/max(c_before['big'],1)*100:.0f}%  >5m {(c_before['big5']-c_after['big5'])/max(c_before['big5'],1)*100:.0f}%")
main()
