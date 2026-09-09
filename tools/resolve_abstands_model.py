#!/usr/bin/env python3
"""决定性判别: 时距模型 d=t(idx)*v  vs  距离模型 d=g(idx)（不乘v）
对同一高速跟车块, 比较两模型在 '距离微分' 上的运动学闭合。
时距模型: d_dot = t'(idx)*idx_dot*v + t(idx)*v_dot
距离模型: d_dot = g'(idx)*idx_dot        (与 v 无关)
真实 d_dot = vrel = vlead - v_ego
取 vrel 显著、idx 连续快速变化的窗来最小化量化噪声 → 哪个残差小即正确。
"""
import glob, json, sys, numpy as np
sys.path.insert(0,"/data/openpilot"); sys.path.insert(0,"/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader

# 时距表
ITAB=np.array(json.load(open('/data/openpilot/ai/tools/abstands_idx_table.json')))
TTAB=np.array(json.load(open('/data/openpilot/ai/tools/abstands_t_table.json')))
def t_at(idx): return float(np.interp(idx, ITAB, TTAB))

SEGS=['20','21','22','23']
def parse(f):
    cur_idx=0.0; cur_vwh=0.0; cur_v=0.0; cur_vlead=None; rows=[]
    for m in LogReader(f):
        w=m.which()
        if w=='can':
            for c in m.can:
                if c.src==2 and c.address==780 and len(c.dat)>=7:
                    cur_idx=float((c.dat[3]|(c.dat[4]<<8))&0x3FF)
                elif c.src==2 and c.address==804 and len(c.dat)>=7:
                    vl=((c.dat[5]|(c.dat[6]<<8))&0x3FF)*0.32
                    cur_vlead=None if vl>=320 else vl
                elif c.address==259 and len(c.dat)>=8:
                    s=((c.dat[2]|(c.dat[3]<<8))&0xFFF)+(((c.dat[3]>>4)|(c.dat[4]<<4))&0xFFF)+((c.dat[5]|(c.dat[6]<<8))&0xFFF)+(((c.dat[6]>>4)|(c.dat[7]<<4))&0xFFF)
                    cur_vwh=s*0.1/4/3.6
        elif w=='carState':
            cur_v=float(m.carState.vEgo); cur_t=m.logMonoTime
            vuse=cur_vwh if cur_vwh>1.0 else cur_v
            if 10<cur_idx<1021 and vuse>5.0 and cur_vlead is not None:
                rows.append((cur_t,cur_idx,vuse,cur_vlead))
    return rows

acc=[]
for sn in SEGS:
    f=f'/data/media/0/realdata/00000004--915ebf086f--{sn}/rlog.zst'
    try: acc+=parse(f); print(f'seg{sn}: {len(parse(f))}',flush=True)
    except Exception as e: print(f'seg{sn} ERR {e}',flush=True)
acc.sort()
traj=[];cur=[]
for i in range(len(acc)):
    if cur and acc[i][0]-cur[-1][0]>5e9: traj.append(cur);cur=[]
    cur.append(acc[i])
if cur:traj.append(cur)

res_t=[]; res_g=[]  # (pred_ddot - vrel)
for tr in traj:
    for a,b in zip(tr,tr[1:]):
        dt=(b[0]-a[0])/1e9
        if dt<=0 or dt>0.05: continue
        ti,xi,vi,vli=a; tj,xj,vj,vlj=b
        dix=xj-xi
        if abs(dix)<1 or abs(dix)>120: continue   # 需要idx快速变化
        vrel=(vli-vli)/1.0  # placeholder
        vrel_true=(vli-vj)  # 用当前vlead - vego(后帧ego)
        # 时距模型 d_dot
        dti=t_at(xi); dtj=t_at(xj)
        ti_dot=(dtj-dti)/dt
        dd_time=ti_dot*vi + dtj*(vj-vi)/dt if dt>0 else 0
        # 距离模型 d_dot: g(idx)未知, 但若g单增, dd与v无关; 比较其随v的依赖用残差即可
        # 这里仅验证时距模型: 若正确, dd_time≈vrel
        res_t.append(dd_time-vrel_true)
print(f'\n时距模型检验帧(需idx快变): {len(res_t)}')
res_t=np.array(res_t)
print(f'  时距模型 d_dot-vrel: mean={res_t.mean():.3f} std={res_t.std():.3f} |e|中位={np.median(np.abs(res_t)):.3f} m/s')
print(f'  真实vrel中位={np.median([ (b[3]-b[2]) for tr in traj for a,b in zip(tr,tr[1:]) ]):.3f} m/s')
