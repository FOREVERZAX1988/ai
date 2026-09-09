#!/usr/bin/env python3
"""(单位修正版)决定性判别: 时距模型 vs 距离模型
对高速跟车块, 重构真实距离 d_true = ∫(vlead-v)dt（起点任意, 取相对量）
测试:
  模型A(时距): d_true 应 = t(idx)*v   → 回归 d_true ~ t(idx)*v 的 slope应≈1
  模型B(距离): d_true 应 = g(idx)不乘v → 回归 d_true ~ idx 的 slope(每米) 应与v无关
判定: 在 v 变化大而 idx 变化相对小的窗内, 看哪个模型解释 d_true 残差更小
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
                    s=((c.dat[2]|(c.dat[3]<<8))&0xFFF)+(((c.dat[3]>>4)|(c.dat[4]<<4))&0xFFF)+((c.dat[5]|(c.dat[6]<<8))&0xFFF)+(((c.dat[6]>>4)|(c.dat[7]<<4))&0xFFF)
                    cur_vwh=s*0.1/4/3.6
        elif w=='carState':
            cur_v=float(m.carState.vEgo); cur_t=m.logMonoTime
            vuse=cur_vwh if cur_vwh>1.0 else cur_v
            if 10<cur_idx<1021 and vuse>5.0 and cur_vlead is not None:
                rows.append((cur_t,cur_idx,vuse,cur_vlead/3.6))  # 全部 m/s
    return rows

SEGS=['20','21','22','23']
acc=[]
for sn in SEGS:
    f=f'/data/media/0/realdata/00000004--915ebf086f--{sn}/rlog.zst'
    try: acc+=parse(f); print(f'seg{sn}: {len(parse(f))}',flush=True)
    except Exception as e: print(f'seg{sn} ERR {e}',flush=True)
acc.sort()
traj=[];cur=[]
for i in range(len(acc)):
    if cur and acc[i][0]-cur[-1][0]>1e9: traj.append(cur);cur=[]
    cur.append(acc[i])
if cur:traj.append(cur)

# 对每块: 计算累计 d_true 相对起点偏移, 以及每帧的 t(idx)*v 相对起点
dataA=[]; dataB=[]
for tr in traj:
    n=len(tr)
    if n<50: continue
    dtrue_cum=0.0; prev=None
    base_idx=tr[0][1]; base_tv=t_at(tr[0][1])*tr[0][2]
    for k,(t,ix,v,vl) in enumerate(tr):
        if prev is not None:
            dt=(t-prev[0])/1e9
            if dt>0 and dt<0.3:
                dtrue_cum+=(vl-prev[2])*dt
        prev=(t,ix,v,vl)
        # 模型A特征: t(idx)*v 相对起点
        dataA.append((ix, t_at(ix)*v - base_tv, dtrue_cum, v))
        # 模型B特征: idx 相对起点(×100放大数值稳定)
        dataB.append((ix, (ix/100 - base_idx/100), dtrue_cum, v))

dataA=np.array(dataA); dataB=np.array(dataB)
print(f'\n样本帧 {len(dataA)}',flush=True)
if len(dataA)<50: sys.exit()
# 模型A: d_true ~ a*(t*v相对) + b, a应≈1
AA=np.column_stack([dataA[:,1],np.ones(len(dataA))])
cA,_,_,_=np.linalg.lstsq(AA,dataA[:,2],rcond=None)
resA=dataA[:,2]-(cA[0]*dataA[:,1]+cA[1])
print(f'模型A时距: d_true = {cA[0]:.3f}*(t·v) + {cA[1]:.2f}  (理想 a=1)',flush=True)
print(f'  A残差 std={resA.std():.2f} m  |e|中位={np.median(np.abs(resA)):.2f} m',flush=True)
# 模型B: d_true ~ b*(idx相对), b=dx/didx
BB=np.column_stack([dataB[:,1],np.ones(len(dataB))])
cB,_,_,_=np.linalg.lstsq(BB,dataB[:,2],rcond=None)
resB=dataB[:,2]-(cB[0]*dataB[:,1]+cB[1])
print(f'模型B距离: d_true = {cB[0]:.3f}*(Δidx/100) + {cB[1]:.2f}  (每100idx=米)',flush=True)
print(f'  B残差 std={resB.std():.2f} m  |e|中位={np.median(np.abs(resB)):.2f} m',flush=True)

# 关键判别: 固定idx窗内, 看残差是否随 v 变化(若模型A对, A残差应与v无关; 若B对, B残差应与v无关)
for lo in [100,200,300]:
    m=(dataA[:,0]>=lo)&(dataA[:,0]<lo+80)
    if m.sum()<30: continue
    ra=resA[m]; rb=resB[m]; v=dataA[m,3]
    # 残差与v的相关
    ca=np.corrcoef(ra,v)[0,1]; cb=np.corrcoef(rb,v)[0,1]
    print(f'idx[{lo}-{lo+80}) n={m.sum():3d}: A残差·v相关={ca:+.2f}  B残差·v相关={cb:+.2f}')
    print(f'    A|e|={np.median(np.abs(ra)):.2f}  B|e|={np.median(np.abs(rb)):.2f} m')
