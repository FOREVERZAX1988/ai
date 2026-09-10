#!/usr/bin/env python3
"""0071/0072 专项扫描（bus2 原厂口径）。
idx: src==2 addr==780 (dat[3]|dat[4]<<8)&0x3FF ; zl: (dat[4]>>5)&7
v_lead_can: src==2 addr==804 ((dat[5]|dat[6]<<8)&0x3FF)*0.32 km/h (<320 有效)
视觉: leadsV3[0].x[0]=d_vis, .v[0]=v_vis, .prob
目的: ①原厂 idx->t 是否分段 ②zl 是否影响映射 ③速度一致性能否推出距离一致
"""
import sys, os, glob, json, numpy as np
sys.path.insert(0,"/data/openpilot"); sys.path.insert(0,"/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader

BASE='/data/media/0/realdata'
IDX_TAB=np.array(json.load(open('/data/openpilot/ai/tools/abstands_idx_table.json')))
T_TAB=np.array(json.load(open('/data/openpilot/ai/tools/abstands_t_table.json')))
def t_old(i): return float(np.interp(i,IDX_TAB,T_TAB))
def t_new(i):
    if i<100: return 0.8
    if i>560: return 6.0
    return 0.008718*i+1.0178

def scan(prefix):
    segs=sorted(f'{BASE}/{d}/rlog.zst' for d in os.listdir(BASE)
                if d.startswith(prefix) and os.path.isfile(f'{BASE}/{d}/rlog.zst'))
    rows=[]; nseg=0
    for f in segs:
        nseg+=1
        ci=0.0; czl=0; cl=-1.0; vwh=0.0; visd=None; visv=0.0; pr=0.0
        try:
            for m in LogReader(f):
                w=m.which()
                if w=='can':
                    for c in m.can:
                        if c.address==259 and len(c.dat)>=8:
                            d=c.dat
                            s=(((d[2]|(d[3]<<8))&0xFFF)+(((d[3]>>4)|(d[4]<<4))&0xFFF)
                               +((d[5]|(d[6]<<8))&0xFFF)+(((d[6]>>4)|(d[7]<<4))&0xFFF))*0.1
                            vwh=s/4*0.2778
                        elif c.src==2 and c.address==780 and len(c.dat)>=7:
                            ci=float((c.dat[3]|(c.dat[4]<<8))&0x3FF); czl=int((c.dat[4]>>5)&7)
                        elif c.src==2 and c.address==804 and len(c.dat)>=7:
                            v=((c.dat[5]|(c.dat[6]<<8))&0x3FF)*0.32
                            if v<320: cl=v
                elif w=='modelV2':
                    ld=m.modelV2.leadsV3
                    if len(ld)>0 and len(ld[0].x)>0:
                        pr=float(ld[0].prob); visd=float(ld[0].x[0])
                        visv=float(ld[0].v[0]) if len(ld[0].v)>0 else 0.0
                elif w=='carState':
                    ve=float(m.carState.vEgo)
                    vuse=vwh if vwh>1.0 else ve
                    if visd is not None and pr>0.5 and 10<ci<1020 and vuse>5.0 and 0<cl<320:
                        rows.append((ci,vuse,visd,visv,cl/3.6,float(czl)))
        except Exception as e:
            print(f'  [warn] {f}: {e}', file=sys.stderr)
    return rows, nseg

ALL={}
for pre in ['00000071','00000072']:
    rows,nseg=scan(pre)
    ALL[pre]=rows
    a=np.array(rows) if rows else np.zeros((0,6))
    print(f'\n===== {pre}  segs={nseg}  paired_frames={len(rows)} =====', flush=True)
    if not len(rows): continue
    idx=a[:,0]; v=a[:,1]; dv=a[:,2]; vv=a[:,3]; vc=a[:,4]; zl=a[:,5]
    tv=dv/v                      # 视觉推出的时距
    print(f'idx  p05/50/95 = {np.percentile(idx,5):.0f}/{np.percentile(idx,50):.0f}/{np.percentile(idx,95):.0f}')
    print(f'v_ego p50={np.median(v):.1f} m/s ({np.median(v)*3.6:.0f}km/h)  d_vis p50={np.median(dv):.1f} m')
    print(f'zl 分布: ' + ' '.join(f'{int(z)}:{int((zl==z).sum())}' for z in sorted(set(zl))))
    # ① idx -> t_vis 曲线（按 idx 分箱）
    print('\n[①] t_vis = d_vis/v_ego  vs  idx 分箱  (窗口±25)')
    print(f'{"idx_bin":>8}{"n":>7}{"t_vis中位":>10}{"t_old":>8}{"t_new":>8}{"t_vis-t_old":>12}{"t_vis-t_new":>12}')
    for c in range(100,1024,100):
        s=(idx>=c-25)&(idx<c+25)
        if s.sum()<30: 
            print(f'{c:>8}{int(s.sum()):>7}{"-":>10}'); continue
        print(f'{c:>8}{int(s.sum()):>7}{np.median(tv[s]):>10.3f}{t_old(c):>8.3f}{t_new(c):>8.3f}'
              f'{np.median(tv[s])-t_old(c):>12.3f}{np.median(tv[s])-t_new(c):>12.3f}')
    # 单直线拟合全部
    if len(idx)>200:
        A=np.polyfit(idx,tv,1); res=tv-np.polyval(A,idx)
        print(f'\n全段单直线拟合 t_vis = {A[0]:.6f}*idx + {A[1]:.3f}  残差: 中位|r|={np.median(np.abs(res)):.3f}s  RMS={np.sqrt((res**2).mean()):.3f}s')
    # ② zl 影响
    print('\n[②] 同 idx 下按 zl 分组 t_vis 中位（检验档位是否改变映射）')
    print(f'{"idx_bin":>8}'+''.join(f'{"zl="+str(int(z)):>11}' for z in sorted(set(zl))))
    for c in range(100,1024,150):
        s0=(idx>=c-50)&(idx<c+50)
        out=f'{c:>8}'
        for z in sorted(set(zl)):
            s=s0&(zl==z)
            out+=f'{np.median(tv[s]):>11.3f}' if s.sum()>=20 else f'{"-":>11}'
        print(out)
    # ③ 速度一致性 vs 距离偏差
    for name,tfun in [('t_old',t_old),('t_new',t_new)]:
        d_stock=np.array([tfun(i)*max(vv,5.0) for i,vv in zip(idx,v)])
        dd=dv-d_stock; av=np.abs(vv-vc)
        print(f'\n[③] 速度一致度分档 (stock={name})')
        print(f'{"|v_vis-v_can|":>16}{"n":>8}{"med(d_vis-d_stock)":>19}{"med|diff|≤5m%":>15}')
        for lo,hi in [(0,0.5),(0.5,1),(1,2),(2,99)]:
            s=(av>=lo)&(av<hi)
            if s.sum()<50: continue
            print(f'{f"{lo}-{hi}":>16}{int(s.sum()):>8}{np.median(dd[s]):>19.1f}{100*np.mean(np.abs(dd[s])<=5):>15.1f}')
        print(f'{"ALL":>16}{len(dd):>8}{np.median(dd):>19.1f}{100*np.mean(np.abs(dd)<=5):>15.1f}')
        print(f'           d_vis中位={np.median(dv):.1f}  d_stock中位={np.median(d_stock):.1f}')
