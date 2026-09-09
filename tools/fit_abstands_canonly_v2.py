#!/usr/bin/env python3
"""方案A-v2: 里程积分法(全帧约束)标定 ACC_Abstandsindex -> 时距表
比v1逐帧差分强: 每个连续跟车块引入初始距离d0, 用累计相对位移int(vrel)dt把全部帧纳入约束。
模型: d_i = t(idx_i)*v_i = d0 + cumrel_i   (cumrel为累计相对位移, m/s*dt)
t(idx) 用节点线性插值。配平滑/单调/锚点正则。
用法: python3 fit_abstands_canonly_v2.py <prefix> <seg1,seg2,..>
"""
import glob, sys, os, numpy as np
from openpilot.tools.lib.logreader import LogReader
BASE='/data/media/0/realdata'
PREFIX=sys.argv[1] if len(sys.argv)>1 else '00000004'
SEGSPEC=sys.argv[2] if len(sys.argv)>2 else ''
if SEGSPEC:
    segs=[f for d in sorted(glob.glob(f'{BASE}/{PREFIX}--*')) if (num:=d.split('--')[-1]) in SEGSPEC.split(',') and os.path.isfile(f'{d}/rlog.zst') for f in [f'{d}/rlog.zst']]
else:
    segs=sorted(glob.glob(f'{BASE}/{PREFIX}--*/rlog.zst'))
print(f'{PREFIX}: {len(segs)} segs',flush=True)

def parse(f):
    cur_idx=0.0;cur_v=0.0;cur_vlead=None;rows=[]
    for m in LogReader(f):
        w=m.which()
        if w=='can':
            for c in m.can:
                if c.src==2 and c.address==780 and len(c.dat)>=7:
                    cur_idx=float((c.dat[3]|(c.dat[4]<<8))&0x3FF)
                elif c.src==2 and c.address==0x324 and len(c.dat)>=7:
                    vl=((c.dat[5])|((c.dat[6]&0x03)<<8))*0.32
                    cur_vlead=None if vl>=320 else vl
        elif w=='carState':
            cur_v=float(m.carState.vEgo);cur_t=m.logMonoTime
            if 0.0<cur_idx<1021.0 and cur_v>2.0 and cur_vlead is not None:
                rows.append((cur_t,cur_idx,cur_v,cur_vlead))
    return rows

all_rows=[]
for f in segs:
    r=parse(f);all_rows+=r
    print(f'  seg{f.split("/")[-2][-3:]}: {len(r)} frames',flush=True)
print(f'总跟车样本: {len(all_rows)}',flush=True)
all_rows.sort()

# 分割轨迹块(>5s间隙)
traj=[];cur=[]
for i in range(len(all_rows)):
    if cur and all_rows[i][0]-cur[-1][0]>5e9:
        traj.append(cur);cur=[]
    cur.append(all_rows[i])
if cur:traj.append(cur)
print(f'连续跟车块: {len(traj)}',flush=True)

# 节点: idx 均匀, 并保证覆盖数据范围
allidx=np.array([r[1] for tr in traj for r in tr])
lo,hi=allidx.min(),allidx.max()
nodes=np.arange(int(lo//10)*10,int(hi//10)*10+11,10).astype(float)
if nodes[0]>lo: nodes=np.insert(nodes,0,lo)
if nodes[-1]<hi: nodes=np.append(nodes,hi)
N=len(nodes)
print(f'时距节点数:{N} idx[{nodes[0]:.0f},{nodes[-1]:.0f}]',flush=True)
B=len(traj)

# 组装 A u = b ; u=[t0..t_{N-1}, d0_0..d0_{B-1}]
rows=[];A=[];b=[]
for bi,tr in enumerate(traj):
    cum=0.0
    prev_t=None;prev_vrel=None
    for j,(t,ix,v,vl) in enumerate(tr):
        vrel=(vl-v)/3.6  # m/s
        if prev_t is not None:
            dt=(t-prev_t)/1e9
            cum+=vrel*dt
        # 线性插值 t(idx)
        x=float(ix)
        k=max(0,min(N-1,int(np.searchsorted(nodes,x,'right')-1)))
        if k>=N-1: k=N-2
        w=(x-nodes[k])/(nodes[k+1]-nodes[k])
        row=np.zeros(N+B)
        row[k]+=v*(1-w);row[k+1]+=v*w
        row[N+bi]-=1.0
        A.append(row);b.append(cum)
        prev_t=t;prev_vrel=vrel
A=np.array(A);b=np.array(b)
print(f'约束矩阵 {A.shape}',flush=True)

# 正则: 平滑二阶差 + 锚点(最小idx t≈0.8) + 单调(Tikhonov)
reg=[]
# 锚: 最小idx节点接近0.8
regA=[];regb=[]
idx0=nodes.argmin()
r=np.zeros(N+B);r[idx0]=1.0;regA.append(r);regb.append(0.8)
# 平滑: 二阶差
for k in range(1,N-1):
    r=np.zeros(N+B);r[k-1]-=1;r[k]+=2;r[k+1]-=1
    regA.append(r);regb.append(0.0)
regA=np.array(regA);regb=np.array(regb)
lam_s=0.5;lam_a=2.0
AA=np.vstack([A,lam_s*regA,lam_a*regA[:1]])
bb=np.concatenate([b,lam_s*regb,lam_a*regb[:1]])
u,res,rank,sv=np.linalg.lstsq(AA,bb,rcond=None)
t_sol=u[:N];d0=u[N:N+B]
# 强制单调累计
"""t的单调性: 用累积最大兜底, 但保持平滑; 这里直接输出原始+单调版对比"""
solc=np.maximum.accumulate(t_sol)
print('\n=== 结果[idx->时距 t(s)] 方案A-v2 里程积分 ===')
print('  idx   t_raw  t_mono')
for x,tr,tm in zip(nodes,t_sol,solc):
    print(f'  {x:5.0f}  {tr:.3f}  {tm:.3f}')
print(f'\n块初始距离d0: {np.round(d0,2)}')
np.savez('/tmp/fit_v2_res.npz',nodes=nodes,t=t_sol,tmono=solc)
