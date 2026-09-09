#!/usr/bin/env python3
"""重新验算时距表: 窗口积分一致性校验 (纯CAN, 轮速做v)
在每段连续跟车块内, 用1s窗口:
   表预测距离变化  d2-d1 = t(idx2)v2 - t(idx1)v1
   实测里程积分    ∫vrel dt = ∫(vlead-v)dt
   两者应一致 => 表(含公式 d=t*v) 正确性的定量证据
输出: 每(idx带,窗口数) 的 表Δd vs 积分Δd 的回归 slope/bias
"""
import glob, json, sys, numpy as np
sys.path.insert(0,"/data/openpilot"); sys.path.insert(0,"/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader

ITAB=np.array(json.load(open('/data/openpilot/ai/tools/abstands_idx_table.json')))
TTAB=np.array(json.load(open('/data/openpilot/ai/tools/abstands_t_table.json')))
def t_at(idx): return float(np.interp(idx, ITAB, TTAB))

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
                    # 四轮轮速 16|12 28|12 40|12 52|12 0.1km/h
                    s=((c.dat[2]|(c.dat[3]<<8))&0xFFF)+(((c.dat[3]>>4)|(c.dat[4]<<4))&0xFFF)+((c.dat[5]|(c.dat[6]<<8))&0xFFF)+(((c.dat[6]>>4)|(c.dat[7]<<4))&0xFFF)
                    cur_vwh=s*0.1/4/3.6
        elif w=='carState':
            cur_v=float(m.carState.vEgo); cur_t=m.logMonoTime
            vuse = cur_vwh if cur_vwh>1.0 else cur_v
            if 10<cur_idx<1021 and vuse>5.0 and cur_vlead is not None:
                rows.append((cur_t,cur_idx,vuse,cur_vlead))  # vlead km/h kept
    return rows

SEGS=['19','20','21','22','23','24','5','6','7']
allr=[]
for sn in SEGS:
    f=f'/data/media/0/realdata/00000004--915ebf086f--{sn}/rlog.zst'
    try:
        r=parse(f); allr+=r
        print(f'seg{sn}: {len(r)}',flush=True)
    except Exception as e: print(f'seg{sn} ERR {e}',flush=True)
allr.sort(); print('总帧',len(allr),flush=True)
traj=[];cur=[]
for i in range(len(allr)):
    if cur and allr[i][0]-cur[-1][0]>5e9: traj.append(cur);cur=[]
    cur.append(allr[i])
if cur:traj.append(cur)

# 窗口(1s, 滑0.5s): 块内累计
W=1.0e9
rows=[]
for tr in traj:
    n=len(tr)
    for st in range(0,n-1):
        # 累积直到跨过1s或idx变化足够大
        j=st
        cum=0.0; prv=None
        for k in range(st,min(st+200,n)):
            t,ix,v,vl=tr[k]
            if prv is not None:
                dt=(tr[k][0]-prv[0])/1e9
                if dt<=0 or dt>0.2: break
                vrel=(prv[3]-prv[2]*3.6)/3.6
                cum+=vrel*dt
            if tr[k][0]-tr[st][0]>=W:
                j=k; break
            prv=tr[k]
        if j<=st+2: continue
        t0,ix0,v0,vl0=tr[st]; t1,ix1,v1,vl1=tr[j]
        d0=t_at(ix0)*v0; d1=t_at(ix1)*v1
        # 表预测距离变化 vs 实测相对位移
        if abs(ix1-ix0)<1: continue
        rows.append((ix0,(ix1+ix0)/2,d1-d0,cum,b'1'))  # last is dummy
rr=np.array([[r[0],r[1],r[2],r[3]] for r in rows])
print(f'窗口数 {len(rr)}',flush=True)
if len(rr)<10: print('窗口太少'); sys.exit(0)
dpred=rr[:,2]; dint=rr[:,3]; idx=rr[:,1]
# 整体回归 dpred ~ a*dint + b
A=np.column_stack([dint,np.ones_like(dint)])
coef,res,_,_=np.linalg.lstsq(A,dpred,rcond=None)
print(f'\n===== 表预测距离变化 vs 里程积分位移 =====')
print(f'整体: dpred = {coef[0]:.3f}*dint + {coef[1]:.2f}  (理想 a=1, b=0)')
resid=dpred-(coef[0]*dint+coef[1])
rmse=np.sqrt(np.mean(resid**2))
print(f'残差 RMSE={rmse:.2f} m  (dint范围 [{dint.min():.1f},{dint.max():.1f}])')
# 按idx带
for lo in [0,100,200,300,400]:
    m=(idx>=lo)&(idx<lo+100)
    if m.sum()>=8:
        A2=np.column_stack([dint[m],np.ones(m.sum())])
        c2,_,_,_=np.linalg.lstsq(A2,dpred[m],rcond=None)
        print(f'  idx[{lo}-{lo+100}): n={m.sum():4d}  slope={c2[0]:.3f} bias={c2[1]:.2f}m')
# 残差 vs idx 简化
print('\n表 t(idx) 在被测 idx 带的均值:')
for lo in [0,100,200,300,400]:
    m=(idx>=lo)&(idx<lo+100)
    if m.sum()>=8:
        mid=np.median(idx[m])
        print(f'  idx带 {lo}-{lo+100} 中心idx={mid:.0f}  t={t_at(mid):.2f}s')
