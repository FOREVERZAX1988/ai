#!/usr/bin/env python3
"""Plan-B 拟合 + 视觉/雷达距离差复核 (2026-09-10)
- 载入统一口径落盘 /tmp/rows_<route>.npy  [idx,v_use,d_vis,v_vis,v_can,zl,d_old,d_new]
- 干净同目标门控: v>=8m/s 且 |v_vis-v_can|<=0.5m/s 且 100<=idx<=560
- 拟合 B:  t(idx)=a*idx+b  (t = d_vis / max(v,5))
   B1 单一池化(全部分支) / B2 仅新分支 / B3 按档位 zl3,zl4
- 对比口径: 旧153表 / 新线性公式(代码现状) / B…  输出 视觉-雷达 距离差 统计
"""
import numpy as np, json, os
OLD=['00000002','00000003','00000004','00000049']
NEW=['00000071','00000072']
ROUTES=OLD+NEW
R={}
for r in ROUTES:
    p=f'/tmp/rows_{r}.npy'
    R[r]=np.load(p) if os.path.exists(p) else np.zeros((0,8))
    print(f'{r}: n={len(R[r])} zl={np.unique(R[r][:,5].astype(int)) if len(R[r]) else []}')
ALL=np.vstack([R[r] for r in ROUTES]) if any(len(R[r]) for r in ROUTES) else np.zeros((0,8))
print(f'ALL n={len(ALL)}')
np.save('/tmp/planB_ALL.npy',ALL)

def gate(X):
    if not len(X): return X
    idx,v,dv,vv,vc,zl,dold,dnew = [X[:,i] for i in range(8)]
    m=(v>=8.0)&(np.abs(vv-vc)<=0.5)&(idx>=100)&(idx<=560)&(dv>0)
    return X[m]
def split_branch(X):
    return X  # caller decides
def fit_line(X):
    idx,v,dv = X[:,0],np.maximum(X[:,1],5.0),X[:,2]
    t=dv/v
    A=np.vstack([idx,np.ones_like(idx)]).T
    sol,res,rk,sv=np.linalg.lstsq(A,t,rcond=None)
    pred=sol[0]*idx+sol[1]
    rms=float(np.sqrt(np.mean((pred-t)**2)))
    return float(sol[0]),float(sol[1]),rms,len(X)
def d_of(a,b,idx,v): return (a*idx+b)*np.maximum(v,5.0)
def stats(name,dv,ds):
    if not len(dv): return
    d=dv-ds; ad=np.abs(d); ratio=ad/np.maximum(ds,1.0)
    print(f'   {name:26s} n={len(dv):7d}  med(vis-rad)={np.median(d):+7.2f}m  med|Δ|={np.median(ad):6.2f}m  %≤5m={100*np.mean(ad<=5):5.1f}%  ratio>30%={100*np.mean(ratio>0.3):5.1f}%')
def bands(dv,ds,label):
    print(f'     -- {label} 按视觉距离分段: 段 d_vis(med) d_rad(med) Δ(med) |Δ|rel% n')
    e=[0,15,25,40,60,90,1e9]
    for i in range(len(e)-1):
        m=(dv>=e[i])&(dv<e[i+1])
        if m.sum()<30: continue
        print(f'        {int(e[i])}-{int(e[i+1]) if e[i+1]<1e9 else 999:>3}: {np.median(dv[m]):6.1f} {np.median(ds[m]):6.1f} {np.median(dv[m]-ds[m]):+6.2f} {100*np.median(np.abs(dv[m]-ds[m])/np.maximum(ds[m],1)):6.1f} {m.sum()}')

print('\n=== 门控统计 ===')
for r in ROUTES:
    g=gate(R[r]); print(f'  {r}: clean={len(g)}/{len(R[r])}')
G=gate(ALL); GOLD=gate(np.vstack([R[r] for r in OLD])); GNEW=gate(np.vstack([R[r] for r in NEW]))
print(f'  池化 clean 全部={len(G)} 旧分支={len(GOLD)} 新分支={len(GNEW)}')
zlG=G[:,5].astype(int)
for z in (3,4):
    m=zlG==z; print(f'    zl={z}: n={m.sum()}')

print('\n=== B 拟合 (t=a*idx+b, 目标 t=d_vis/max(v,5)) ===')
a1,b1,r1,n1=fit_line(G);   print(f'  B1 池化全部 : t={a1:.6f}*idx+{b1:+.4f}  RMS={r1:.3f}s n={n1}')
a2,b2,r2,n2=fit_line(GNEW);print(f'  B2 仅新分支 : t={a2:.6f}*idx+{b2:+.4f}  RMS={r2:.3f}s n={n2}')
a3,b3,r3,n3=fit_line(GOLD);print(f'  B3 仅旧分支 : t={a3:.6f}*idx+{b3:+.4f}  RMS={r3:.3f}s n={n3}')
BZ={}
for z in (3,4):
    m=zlG==z
    if m.sum()>200:
        a,b,r,n=fit_line(G[m]); BZ[z]=(a,b); print(f'  B4 zl={z}   : t={a:.6f}*idx+{b:+.4f}  RMS={r:.3f}s n={n}')
json.dump({'B1':[a1,b1],'B2_new':[a2,b2],'B3_old':[a3,b3],'B4_zl':{str(k):v for k,v in BZ.items()}},
          open('/tmp/planB_fit.json','w'),indent=1)
B1=(a1,b1)
print('  参考: 旧153表≈ t=0.008951*idx+0.1625 ; 代码新公式 t=0.008718*idx+1.0178 ; 上轮跨分支最优 t=0.008617*idx+0.401')

def evalall(label, Gsel, dolds, dnews, tag):
    print(f'\n=== 视觉 − 雷达 距离差：{label} (集={tag}) ===')
    stats('旧153表(现状历史)', Gsel[:,2], Gsel[:,6])
    stats('新线性(代码现状)',   Gsel[:,2], Gsel[:,7])
    a,b=B1[0],B1[1];        stats(f'B1 池化全部', Gsel[:,2], d_of(a,b,Gsel[:,0],Gsel[:,1]))
    a,b=a2,b2;              stats(f'B2 新分支拟合(样本内/外取决集)', Gsel[:,2], d_of(a,b,Gsel[:,0],Gsel[:,1]))
    a,b=a3,b3;              stats(f'B3 旧分支拟合', Gsel[:,2], d_of(a,b,Gsel[:,0],Gsel[:,1]))
    # 按档位选表
    ds=np.zeros(len(Gsel))
    zl=Gsel[:,5].astype(int)
    for z,(a,b) in BZ.items():
        m=zl==z; ds[m]=d_of(a,b,Gsel[m,0],Gsel[m,1])
    other=~np.isin(zl,list(BZ.keys()))
    if other.sum():
        a,b=B1[0],B1[1]; ds[other]=d_of(a,b,Gsel[other,0],Gsel[other,1])
    stats('B4 按档位选表(zl3/zl4)', Gsel[:,2], ds)
    return ds

ds_B1_pool = evalall('口径对比', G, None,None,'全部池化')
evalall('口径对比', GNEW, None,None,'新分支 0071/0072')
evalall('口径对比', GOLD, None,None,'旧分支 0002/3/4/49')

print('\n=== 分段细节（B1 池化 / B2 新分支） ===')
bands(G[:,2], d_of(B1[0],B1[1],G[:,0],G[:,1]),'B1')
bands(G[:,2], d_of(a2,b2,G[:,0],G[:,1]),'B2')
bands(G[:,2], G[:,6],'旧153表')
bands(G[:,2], G[:,7],'新线性')

print('\n=== 逐 route（B1 / 最新线性B2） ===')
for r in ROUTES:
    g=gate(R[r])
    if not len(g): continue
    print(f'  {r} n={len(g)}')
    stats('  旧153表', g[:,2], g[:,6])
    stats('  新线性  ', g[:,2], g[:,7])
    stats('  B1池化  ', g[:,2], d_of(B1[0],B1[1],g[:,0],g[:,1]))
    stats('  B2新分支', g[:,2], d_of(a2,b2,g[:,0],g[:,1]))
print('\nDONE')
