#!/usr/bin/env python3
"""验算旧时距表: 校验 idx->时距 t Table 是否满足运动学闭合
检验: d = t(idx)*v ; 要求 d_dot = vrel = (vlead - v)/3.6   (全帧, 轮速做v)
若旧表正确, 差分残差应小且无系统偏差。
"""
import glob, json, sys, numpy as np
sys.path.insert(0,"/data/openpilot"); sys.path.insert(0,"/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader

ITAB=json.load(open('/data/openpilot/ai/tools/abstands_idx_table.json'))
TTAB=json.load(open('/data/openpilot/ai/tools/abstands_t_table.json'))
def t_at(idx):
    ia=np.array(ITAB); ta=np.array(TTAB)
    return float(np.interp(idx, ia, ta))

def parse(f):
    cur_idx=0.0; cur_vwh=0.0; cur_v=0.0; cur_vlead=None; rows=[]
    for m in LogReader(f):
        w=m.which()
        if w=='can':
            for c in m.can:
                if c.src==2 and c.address==780 and len(c.dat)>=7:
                    cur_idx=float((c.dat[3]|(c.dat[4]<<8))&0x3FF)
                elif c.src==2 and c.address==0x324 and len(c.dat)>=7:
                    vl=((c.dat[5])|((c.dat[6]&0x03)<<8))*0.32
                    cur_vlead=None if vl>=320 else vl
                elif c.address==0x103 and len(c.dat)>=4:
                    raw=((c.dat[3]&0x0F)<<8|c.dat[2])&0x0FFF
                    if raw*0.1<300: cur_vwh=raw*0.1/3.6
        elif w=='carState':
            cur_v=float(m.carState.vEgo); cur_t=m.logMonoTime
            vuse = cur_vwh if cur_vwh>0 else cur_v
            if 0.0<cur_idx<1021.0 and vuse>5.0 and cur_vlead is not None:
                rows.append((cur_t,cur_idx,vuse,cur_vlead/3.6,cur_vlead))
    return rows

segs=['19','20','21','22','23','24','5','6','7']
allr=[]
for sn in segs:
    f=f'/data/media/0/realdata/00000004--915ebf086f--{sn}/rlog.zst'
    try: r=parse(f); allr+=r; print(f'seg{sn}: {len(r)} frames',flush=True)
    except Exception as e: print(f'seg{sn} ERR {e}')
allr.sort()
print(f'总跟车帧: {len(allr)}',flush=True)

# 连续块, 逐帧差分 d_dot vs vrel
traj=[];cur=[]
for i in range(len(allr)):
    if cur and allr[i][0]-cur[-1][0]>5e9: traj.append(cur);cur=[]
    cur.append(allr[i])
if cur:traj.append(cur)

diffs=[]; res=[]; vels=[]
for tr in traj:
    for a,b in zip(tr,tr[1:]):
        _,ix1,v1,vl1,_=a; _,ix2,v2,vl2,_=b
        if abs(ix1-ix2)<3: continue          # 只取idx有变化的, 降低量化噪声
        dt=(b[0]-a[0])/1e9
        if dt<=0 or dt>0.3: continue
        d1=t_at(ix1)*v1; d2=t_at(ix2)*v2
        dd_dt=(d2-d1)/dt
        vrel=(vl1-v1)   # m/s
        diffs.append((ix1,v1,vl1,dd_dt,vrel,d1,d2))
res=np.array([[x[3],x[4],x[5]] for x in diffs])
print(f'\n差分帧(表预测 vs 实测vrel): {len(diffs)}')
if len(res):
    ddpred=res[:,0]; vrel=res[:,1]
    r2=1-np.sum((ddpred-vrel)**2)/np.sum((vrel-vrel.mean())**2)
    print(f'R2(d_dot~vrel) = {r2:.3f}')
    print(f'残差mean={np.mean(ddpred-vrel):.3f}  std={np.std(ddpred-vrel):.3f} m/s')
    print(f'vrel范围: {vrel.min():.2f}..{vrel.max():.2f} m/s')
    # 残差 vs idx 分段
    idxs=np.array([x[0] for x in diffs])
    for lo in [0,100,200,300,400]:
        mask=(idxs>=lo)&(idxs<lo+100)
        if mask.sum()>20:
            e=vrel[mask]-ddpred[mask]
            print(f'  idx[{lo}-{lo+100}): n={mask.sum():4d} bias={e.mean():+.3f} std={e.std():.3f} m/s')
