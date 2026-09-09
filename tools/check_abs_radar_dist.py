#!/usr/bin/env python3
"""绝对尺度验证: 当 radarState 真有雷达轨道(radar=True)时, 直接对比
  雷达轨道距离 dRel_radar  vs 表时距公式 d=t(idx)*vEgo
解决差分校验无法判定的绝对偏差(REFIT说-17%, CALIB说距离模型)
"""
import json, sys, numpy as np
sys.path.insert(0,"/data/openpilot"); sys.path.insert(0,"/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader

ITAB=np.array(json.load(open('/data/openpilot/ai/tools/abstands_idx_table.json')))
TTAB=np.array(json.load(open('/data/openpilot/ai/tools/abstands_t_table.json')))
def t_at(idx): return float(np.interp(idx, ITAB, TTAB))

# seg21 已知有 radar=True 帧(REFIT)
f='/data/media/0/realdata/00000004--915ebf086f--21/rlog.zst'
cur_idx=0; cur_v=0; matched=[]
for m in LogReader(f):
    w=m.which()
    if w=='can':
        for c in m.can:
            if c.src==2 and c.address==780 and len(c.dat)>=7:
                cur_idx=float((c.dat[3]|(c.dat[4]<<8))&0x3FF)
    elif w=='carState':
        cur_v=float(m.carState.vEgo)
        cur_rs=m
    elif w=='radarState':
        ld=m.radarState.leadOne
        if ld.radar and cur_idx>10 and cur_v>5:
            d_radar=ld.dRel; v_ego=cur_v
            d_tab=t_at(cur_idx)*v_ego
            matched.append((cur_idx, cur_v, d_tab, d_radar, ld.vRel))
print('seg21 雷达轨道匹配帧数:', len(matched))
if len(matched):
    a=np.array(matched)
    ratios=a[:,2]/a[:,3]   # d_tab / d_radar
    err=(a[:,2]-a[:,3])/a[:,3]*100
    print(f'idx范围 {a[:,0].min():.0f}-{a[:,0].max():.0f}  vEgo {a[:,1].min()*3.6:.0f}-{a[:,1].max()*3.6:.0f} km/h')
    print(f'表/雷达 距离比: 中位 {np.median(ratios):.3f}')
    print(f'表-雷达 误差%: 中位 {np.median(err):.1f}%  (负=表低估=REFIT主张; 正=表高估)')
    print('采样:')
    for ix,v,dt,dr,vr in a[::max(1,len(a)//10)]:
        print(f'  idx={ix:4.0f} v={v*3.6:5.1f} 表d={dt:6.1f}m 雷达d={dr:6.1f}m  vRel={vr:+.2f}m/s')
