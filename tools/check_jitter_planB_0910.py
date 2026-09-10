#!/usr/bin/env python3
"""方案B 拟合后「距离反复横跳」检验 (2026-09-10)
口径: old153 / newcode(代码现状,含0.8s-6.0s伪分段) / newline(同斜率纯直线) / B1 / B4
指标: (a) 连续帧原厂距离抖动 |Δd|  (b) A2 融合后 dRel 抖动  (c) A2 模式(替换/混合)翻转率
输入: /tmp/rowsC_<route>.npy  [idx,v_use,d_vis,v_vis,v_can,zl,d_old,d_newcode,seg,k]
A2 判据两种口径都算（2026-09-10 判据物理化前后对比）：
  rel = |d_vis - d_stock| / d_stock   = |Δt|/t        <- 新代码（距离域）
  idx = |vis_idx - stock_idx| / idx   = |Δt|/(t-B)    <- 旧代码（idx 域，阈值随距离变严）
"""
import numpy as np, json, os, re

ROUTES=['00000004','00000071','00000072','00000049']
_c = open('/data/openpilot/openpilot/selfdrive/controls/radard.py',encoding='utf-8').read()
B1=(float(re.search(r"MACAN_B1_T_A = ([\d.]+)",_c).group(1)),
    float(re.search(r"MACAN_B1_T_B = ([\d.]+)",_c).group(1)))
REL_TH=float(re.search(r"MACAN_A2_REL_TH = ([\d.]+)",_c).group(1))
# B4（按档位两条线）**未落地**，仅作对照；取值来自 MLB_MACAN_PLANB_FIT_0910.md §1
# （拟合脚本 fit_planB_residual_0910.py 的输出 /tmp/planB_fit.json 机器重启后已清）
B4={3:(0.008741,0.727), 4:(0.008414,0.333)}
A_NEW,B_NEW=0.008718,1.0178
IDXT=np.array(json.load(open('/data/openpilot/ai/tools/abstands_idx_table.json')))
TT=np.array(json.load(open('/data/openpilot/ai/tools/abstands_t_table.json')))

def load(r):
    p=f'/tmp/rowsC_{r}.npy'
    return np.load(p) if os.path.exists(p) else np.zeros((0,10))

def formulas(X):
    idx=X[:,0]; v=np.maximum(X[:,1],5.0); zl=X[:,5].astype(int)
    ab=np.where(zl==3,B4[3][0],B4[4][0]); bb=np.where(zl==3,B4[3][1],B4[4][1])
    return {'old153':X[:,6],'newcode':X[:,7],
            'newline':(A_NEW*idx+B_NEW)*v,
            'B1':(B1[0]*idx+B1[1])*v,
            'B4':(ab*idx+bb)*v}, idx, zl, np.maximum(X[:,1],1e-6)

def inv_idx(t,key,zl):
    """时距 t → idx（与各口径一致；newcode 保留代码里的 t<=0.8→100 / t>=6→561 钳位）"""
    if key=='old153':  return np.interp(t,TT,IDXT)
    if key=='newline': return (t-B_NEW)/A_NEW
    if key=='B1':      return (t-B1[1])/B1[0]
    if key=='B4':      return (t-np.where(zl==3,B4[3][1],B4[4][1]))/np.where(zl==3,B4[3][0],B4[4][0])
    if key=='newcode':
        r=(t-B_NEW)/A_NEW
        return np.where(t<=0.8,100.0,np.where(t>=6.0,561.0,r))
    return np.zeros_like(t)

def jit(d,cont):
    dd=np.abs(np.diff(d))[cont]
    if len(dd)==0: return None
    return (len(dd),np.median(dd),np.percentile(dd,90),np.percentile(dd,99),
            1000*np.mean(dd>2),1000*np.mean(dd>5),1000*np.mean(dd>10))

def sim(d_stock,key,idx,zl,dv,v,mode='rel'):
    """复刻 radard._macan_fuse_leads 的 A2：判据 → w → 分段视觉权 → 融合距离
    mode='rel' 新代码（距离域 rel=|d_vis-d_stock|/d_stock）
    mode='idx' 旧代码（idx 域 ratio=|vis_idx-stock_idx|/idx=|Δt|/(t-B)）"""
    if mode=='rel':
      crit=np.abs(dv-d_stock)/np.maximum(d_stock,1.0)
    else:
      tvis=dv/v
      vis_idx=inv_idx(tvis,key,zl)
      with np.errstate(divide='ignore',invalid='ignore'):
          crit=np.abs(vis_idx-idx)/idx
      crit=np.nan_to_num(crit,nan=0.0,posinf=0.0)
    w=np.minimum(0.7+(crit/0.30)*0.3,1.0)
    df=np.where(dv<15,0.5,np.where(dv<40,1.17,np.where(dv<60,1.0,0.83)))
    w_vis=np.minimum((1.0-w)*df,0.5)
    return crit,(1.0-w_vis)*d_stock+w_vis*dv

print('='*118)
print(f"B1: t={B1[0]:.6f}*idx{B1[1]:+.3f}   B4: zl3 t={B4[3][0]:.6f}*idx{B4[3][1]:+.3f} | zl4 t={B4[4][0]:.6f}*idx{B4[4][1]:+.3f}")
print("newcode = 代码现状 0.008718/+1.0178，但 idx<100→0.8s、idx>560→6.0s 伪分段；newline = 同斜率去掉伪分段")
ALL=[]
for r in ROUTES:
    X=load(r)
    if not len(X): print(f'{r}: (无 rowsC 数据)'); continue
    ALL.append(X)
    F,idx,zl,v=formulas(X); dv=X[:,2]; cont=(np.diff(X[:,8])==0)&(np.diff(X[:,9])==1)
    didx=np.abs(np.diff(idx))[cont]; sm=didx<=3
    print(f"\n### route {r}  n={len(X)}  连续帧对={int(cont.sum())}  |Δidx| 中位={np.median(didx):.0f} P90={np.percentile(didx,90):.0f} >20 占比={100*np.mean(didx>20):.1f}%")
    print(f'  {"口径":9s} {"med|Δd|":>8s} {"P90":>7s} {"P99":>8s} {"/1k >2m":>8s} {"/1k >5m":>8s} {"/1k >10m":>9s} | 平滑帧(|Δidx|≤3): med P99 /1k>5m')
    for key,d in F.items():
        n,med,p90,p99,g2,g5,g10=jit(d,cont); dds=np.abs(np.diff(d))[cont][sm]
        print(f'  {key:9s} {med:8.2f} {p90:7.2f} {p99:8.2f} {g2:8.1f} {g5:8.1f} {g10:9.1f} | {np.median(dds):8.2f} {np.percentile(dds,99):7.2f} {1000*np.mean(dds>5):8.1f}')
    for b in (100.0,571.0):
        cr=(((idx[:-1]<b)&(idx[1:]>=b))|((idx[:-1]>=b)&(idx[1:]<b)))&cont
        if cr.sum():
            j=lambda k: np.median(np.abs(np.diff(F[k]))[cr])
            print(f'   [伪分段 idx={int(b)}] 跨界帧={int(cr.sum()):4d}  跨步中位 newcode={j("newcode"):6.1f}m  newline={j("newline"):6.1f}m  B1={j("B1"):6.1f}m  old153={j("old153"):6.1f}m')
    for mode,label in (('rel','物理域rel(新代码)'),('idx','idx域(旧代码)')):
        print(f'  --- A2 融合[判据 {label}]（复刻 radard 逻辑；连续权重输出） ---')
        print(f'  {"口径":9s} {"替换率%":>7s} {"med(vis-rad)":>12s} {"融合med|Δd|":>12s} {"融合P99":>8s} {"/1k>2m":>8s} {"模式翻转/1k":>10s}')
        for key,d in F.items():
            crit,fused=sim(d,key,idx,zl,dv,v,mode)
            jf=jit(fused,cont)
            flip=(np.abs(np.diff(np.sign(crit-0.30)))>0)[cont]
            print(f'  {key:9s} {100*np.mean(crit>0.30):7.1f} {np.median(dv-d):+12.2f} {jf[1]:12.2f} {jf[3]:8.2f} {jf[4]:8.1f} {1000*flip.mean():10.1f}')

if ALL:
    X=np.vstack(ALL); F,idx,zl,v=formulas(X); dv=X[:,2]
    # 跨段拼接后仅保留同为连续帧的对比（段边界已排除）
    cont=(np.diff(X[:,8])==0)&(np.diff(X[:,9])==1)
    print(f"\n### 池化 n={len(X)} 连续帧对={int(cont.sum())}")
    print(f'  {"口径":9s} {"med|Δd|":>8s} {"P99":>8s} {"/1k >5m":>8s} | {"替换率%":>7s} {"med(vis-rad)":>12s} {"融合med|Δd|":>12s} {"融合P99":>8s} {"模式翻转/1k":>10s}')
    for mode in ('rel','idx'):
        print(f'  [A2 判据={mode}]')
        for key,d in F.items():
            n,med,p90,p99,g2,g5,g10=jit(d,cont)
            crit,fused=sim(d,key,idx,zl,dv,v,mode); jf=jit(fused,cont)
            flip=(np.abs(np.diff(np.sign(crit-0.30)))>0)[cont]
            print(f'  {key:9s} {med:8.2f} {p99:8.2f} {g5:8.1f} | {100*np.mean(crit>0.30):7.1f} {np.median(dv-d):+12.2f} {jf[1]:12.2f} {jf[3]:8.2f} {1000*flip.mean():10.1f}')
print('\nDONE')
