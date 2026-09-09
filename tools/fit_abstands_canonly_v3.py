#!/usr/bin/env python3
"""方案A-v3: 纯CAN里程积分标定(idx->时距 t)
- vEgo 用轮速 ESP_VL_Radgeschw(ESP_03 0x103, 16|12@1+ 0.1km/h) 而非 carState.vEgo(校验+替代)
- vlead 用 ACC_04(0x324) ACC_Geschw_Zielfahrzeug (40|10 *0.32 km/h, 无目标=327.36)
- idx 用 ACC_02(0x30c) ACC_Abstandsindex (24|10, [1|1021])
模型: d_i = t(idx_i)*v_i = d0_j + cumrel_i (块内里程积分), t(idx) 节点线性插值
用法: python3 fit_abstands_canonly_v3.py <prefix> <seg1,seg2,...>
"""
import glob, sys, os, numpy as np
sys.path.insert(0,"/data/openpilot"); sys.path.insert(0,"/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader
BASE='/data/media/0/realdata'
PREFIX=sys.argv[1] if len(sys.argv)>1 else '00000004'
SEGSPEC=sys.argv[2] if len(sys.argv)>2 else ''
if SEGSPEC:
    segs=[f'{d}/rlog.zst' for d in sorted(glob.glob(f'{BASE}/{PREFIX}--*')) if d.split('--')[-1] in SEGSPEC.split(',') and os.path.isfile(f'{d}/rlog.zst')]
else:
    segs=sorted(glob.glob(f'{BASE}/{PREFIX}--*/rlog.zst'))
print(f'{PREFIX}: {len(segs)} segs',flush=True)

def parse(f):
    cur_idx=0.0; cur_v=0.0; cur_vwh=0.0; cur_vlead=None; rows=[]
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
                    vw=raw*0.1
                    if vw<300: cur_vwh=vw/3.6   # m/s
        elif w=='carState':
            cur_v=float(m.carState.vEgo); cur_t=m.logMonoTime
            # 用轮速做主速度; 若无轮速(初段)退回 carState.vEgo
            vuse = cur_vwh if cur_vwh>0 else cur_v
            if 0.0<cur_idx<1021.0 and vuse>0.5 and cur_vlead is not None:
                rows.append((cur_t,cur_idx,vuse,cur_vlead,cur_v))
    return rows

all_rows=[]
for f in segs:
    r=parse(f); all_rows+=r
    print(f'  seg{os.path.basename(os.path.dirname(f)).split("--")[-1]}: {len(r)} frames',flush=True)
print(f'总跟车样本: {len(all_rows)}',flush=True)
all_rows.sort()
if not all_rows: print('无样本'); sys.exit(0)

traj=[];cur=[]
for i in range(len(all_rows)):
    if cur and all_rows[i][0]-cur[-1][0]>5e9: traj.append(cur);cur=[]
    cur.append(all_rows[i])
if cur:traj.append(cur)
print(f'连续跟车块: {len(traj)}',flush=True)

allidx=np.array([r[1] for tr in traj for r in tr])
lo,hi=allidx.min(),allidx.max()
print(f'idx范围: [{lo:.0f},{hi:.0f}]',flush=True)
nodes=np.arange(int(lo//5)*5,int(hi//5)*5+6,5).astype(float)
if nodes[0]>lo: nodes=np.insert(nodes,0,lo)
if nodes[-1]<hi: nodes=np.append(nodes,hi)
N=len(nodes); B=len(traj)
print(f'节点数:{N} 块数:{B}',flush=True)
if N<3: print('节点太少'); sys.exit(0)

A=[];b=[]
for bi,tr in enumerate(traj):
    cum=0.0; prev_t=None
    for j,(t,ix,v,vl,v2) in enumerate(tr):
        vrel=(vl/3.6-v)   # m/s
        if prev_t is not None:
            dt=(t-prev_t)/1e9
            cum+=vrel*dt
        x=float(ix)
        k=int(np.searchsorted(nodes,x,'right')-1); k=max(0,min(N-2,k))
        w=(x-nodes[k])/(nodes[k+1]-nodes[k])
        row=np.zeros(N+B)
        row[k]+=v*(1-w); row[k+1]+=v*w
        row[N+bi]-=1.0
        A.append(row); b.append(cum)
        prev_t=t
A=np.array(A); b=np.array(b)
print(f'约束矩阵 {A.shape}',flush=True)

# 平滑 + 锚点 + 单调 正则
regA=[];regb=[]
r=np.zeros(N+B); r[0]=1.0; regA.append(r); regb.append(0.8)  # 锚: 最近idx t~0.8s
for k in range(1,N-1):
    r=np.zeros(N+B); r[k-1]-=1; r[k]+=2; r[k+1]-=1
    regA.append(r); regb.append(0.0)
regA=np.array(regA); regb=np.array(regb)
lam_s=0.5; lam_a=3.0
AA=np.vstack([A,lam_s*regA,lam_a*regA[:1]])
bb=np.concatenate([b,lam_s*regb,lam_a*regb[:1]])
u,res,rank,sv=np.linalg.lstsq(AA,bb,rcond=None)
t_sol=u[:N]; d0=u[N:N+B]
solc=np.maximum.accumulate(t_sol)
print('\n=== 结果 [idx -> 时距 t(s)] 方案A-v3 (轮速里程积分) ===')
print('  idx    t_raw   t_mono')
for x,tr,tm in zip(nodes,t_sol,solc):
    print(f'  {x:6.0f}  {tr:6.3f}  {tm:6.3f}')
print(f'\n块初始距离d0(m): {np.round(d0,2)}')
np.savez('/tmp/fit_v3_res.npz',nodes=nodes,t=t_sol,tmono=solc)
# 距离=时距*速度 样本统计(供校验)
print('\n校验: 采样点 idx->估算距离 = t(idx)*vEgo')
for tr in traj[:3]:
    for t,ix,v,vl,v2 in tr[::50]:
        k=int(np.searchsorted(nodes,ix,'right')-1); k=max(0,min(N-2,k))
        w=(ix-nodes[k])/(nodes[k+1]-nodes[k])
        tval=solc[k]*(1-w)+solc[k+1]*w
        print(f'  idx={ix:5.0f} v={v*3.6:5.1f}km/h vlead={vl:5.1f} t={tval:5.2f}s d={tval*v:5.1f}m vrel={vl/3.6-v:5.2f}m/s')
