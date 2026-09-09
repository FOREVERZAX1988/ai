#!/usr/bin/env python3
"""方案A：纯CAN标定 ACC_Abstandsindex -> 时距表（不用视觉距离）
闭合: d = t(idx)*vEgo ; d_dot = vrel = (vlead - vEgo)/3.6
用法: python3 ai/tools/fit_abstands_canonly.py <route_prefix> [seg1,seg2,...]
"""
import glob, sys, os, numpy as np
from openpilot.tools.lib.logreader import LogReader

BASE='/data/media/0/realdata'
PREFIX = sys.argv[1] if len(sys.argv)>1 else "00000004"
SEGSPEC = sys.argv[2] if len(sys.argv)>2 else ""

if SEGSPEC:
    segs=[]
    for d in sorted(glob.glob(f'{BASE}/{PREFIX}--*')):
        num=d.split('--')[-1]
        if num in SEGSPEC.split(',') and os.path.isfile(f'{d}/rlog.zst'):
            segs.append(f'{d}/rlog.zst')
else:
    segs = sorted(glob.glob(f'{BASE}/{PREFIX}--*/rlog.zst'))
print(f'{PREFIX}: {len(segs)} segs', flush=True)

def parse(f):
    cur_idx=0.0; cur_v=0.0; cur_vlead=None
    rows=[]
    for m in LogReader(f):
        w=m.which()
        if w=='can':
            for c in m.can:
                if c.src==2 and c.address==780 and len(c.dat)>=7:
                    cur_idx=float((c.dat[3]|(c.dat[4]<<8))&0x3FF)
                elif c.src==2 and c.address==0x324 and len(c.dat)>=7:
                    vl=((c.dat[5])|((c.dat[6]&0x03)<<8))*0.32
                    cur_vlead = None if vl>=320 else vl
        elif w=='carState':
            cur_v=float(m.carState.vEgo)
            cur_t=m.logMonoTime
            if 0.0<cur_idx<1021.0 and cur_v>2.0 and cur_vlead is not None:
                rows.append((cur_t, cur_idx, cur_v, cur_vlead))
    return rows

all_rows=[]
for f in segs:
    r=parse(f)
    all_rows+=r
    print(f'  seg{f.split("/")[-2][-3:]}: {len(r)} frames', flush=True)
print(f'\n总跟车样本: {len(all_rows)}', flush=True)
if not all_rows:
    print('无有效样本'); sys.exit(0)

all_rows.sort()
traj=[]; cur=[]
for i in range(len(all_rows)):
    if cur and all_rows[i][0]-cur[-1][0] > 5e9:
        traj.append(cur); cur=[]
    cur.append(all_rows[i])
if cur: traj.append(cur)
print(f'连续跟车轨迹块: {len(traj)}', flush=True)

cons=[]
for tr in traj:
    for a,b in zip(tr,tr[1:]):
        ti,ixi,vi,vli=a; tj,ixj,vj,vlj=b
        if abs(ixi-ixj)<5: continue
        dt=(tj-ti)/1e9
        if dt<=0 or dt>0.5: continue
        cons.append((ixi,ixj,vi,vj,(vli-vi),dt))
print(f'差分约束: {len(cons)}', flush=True)
if not cons:
    print('无差分约束'); sys.exit(0)

idx_nodes=sorted(set([int(c[0]) for c in cons]+[int(c[1]) for c in cons]))
nodes=[]
for x in idx_nodes:
    if nodes and x-nodes[-1]<=5: nodes[-1]=x
    else: nodes.append(x)
N=len(nodes)
print(f'节点数: {N} (idx {nodes[0]}-{nodes[-1]})', flush=True)
if N<3:
    print('节点太少'); sys.exit(0)

A=[]; b=[]
for ixi,ixj,vi,vj,vrel,dt in cons:
    ki=max(0,min(N-1,np.searchsorted(nodes,ixi,'right')-1))
    kj=max(0,min(N-1,np.searchsorted(nodes,ixj,'right')-1))
    row=np.zeros(N)
    row[ki]-=vi/3.6
    row[kj]+=vj/3.6
    A.append(row); b.append((vrel/3.6)*dt)
A=np.array(A); b=np.array(b)
print(f'方程组矩阵 {A.shape}', flush=True)

lam=0.5
ATA=A.T@A + lam*np.eye(N)
anchor=np.zeros(N); anchor[0]=1.0
# 锚定近贴车节点 t≈0.8s（只用2个最强约束的均值作为软约束）
ATA=ATA+10.0*np.outer(anchor,anchor)
ATb=A.T@b + 10.0*0.8*anchor
try:
    sol=np.linalg.solve(ATA,ATb)
except Exception as e:
    print('solve fail', e); sys.exit(0)
solc=np.maximum.accumulate(sol)
print('\n=== 结果: idx -> 时距 t(s) [方案A 纯CAN] ===')
print('  idx    t')
for x,t in zip(nodes,solc):
    print(f'  {x:5d}  {t:.3f}')
