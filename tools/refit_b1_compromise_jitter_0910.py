#!/usr/bin/env python3
"""(a) 单表系数折中扫描(旧/新分支都不许变差太多) (b) 连续帧反复横跳复核(物理域判据)"""
import numpy as np, os, json
OLD=['00000002','00000003','00000004','00000049']; NEW=['00000071','00000072']; ROUTES=OLD+NEW
L=lambda p: np.load(p) if os.path.exists(p) else np.zeros((0,8))
R={r:L(f'/tmp/rows_{r}.npy') for r in ROUTES}
ALL=np.vstack([R[r] for r in ROUTES]); OLDX=np.vstack([R[r] for r in OLD]); NEWX=np.vstack([R[r] for r in NEW])
def gate(X):
    idx,v,dv,vv,vc=X[:,0],np.maximum(X[:,1],5.0),X[:,2],X[:,3],X[:,4]
    m=(v>=8.0)&(np.abs(vv-vc)<=0.5)&(idx>=100)&(idx<=560)&(dv>0)
    return idx[m],v[m],dv[m]
PO=gate(ALL); POLD=gate(OLDX); PNEW=gate(NEWX)
def ev(S,a,b):
    idx,v,dv=S; d=(a*idx+b)*v; ad=np.abs(dv-d)
    return np.median(ad),100*np.mean(ad<=5),100*np.mean(ad/np.maximum(d,1)>0.3),np.median(dv-d)
print("=== 单表系数扫描 (目标: 池化最优 & 两分支都不劣化) ===")
print("   a        b     | 池化 med|Δ| ≤5m% r30%   | 旧分支 med|Δ| ≤5m%   | 新分支 med|Δ| ≤5m%  折中指标max分支medΔ")
best=None
for a in (0.00870,0.00880,0.00890,0.00900,0.00910):
    for b in (0.16,0.20,0.24,0.28,0.32):
        mp,sp,rp,_=ev(PO,a,b); mo,so,ro,_=ev(POLD,a,b); mn,sn,rn,_=ev(PNEW,a,b)
        w=max(mo,mn)
        if best is None or w<best[0]: best=(w,a,b,mp,sp,mo,so,mn,sn)
        if abs(b*100-round(b*100))<1: print(f"  {a:.5f} {b:+.2f} | {mp:5.2f} {sp:5.1f} {rp:4.1f}   | {mo:5.2f} {so:5.1f}   | {mn:5.2f} {sn:5.1f}   {w:5.2f}")
w,a,b,mp,sp,mo,so,mn,sn=best
print(f"\n  折中最优(最小化两分支最大 med|Δ|): a={a:.5f} b={b:+.3f}  池化med|Δ|={mp:.2f} 旧={mo:.2f} 新={mn:.2f}")
CAND={'现行B1(0.008969/0.332)':(0.008969,0.332),'旧153表(0.008951/0.1625)':(0.008951,0.1625),
      'C均值拟合(0.009104/0.182)':(0.009104,0.1819),'折中':(a,b)}
print("\n=== 四候选 × 三个集 (med|Δ| / ≤5m% / ratio>30% / 偏差med) ===")
for name,(aa,bb) in CAND.items():
    line=f"  {name:26s}"
    for lab,S in (('池化',PO),('旧分支',POLD),('新分支',PNEW)):
        md,sp5,r30,bias=ev(S,aa,bb); line+=f" | {lab} {md:5.2f}m {sp5:5.1f}% {r30:4.1f}% bias{bias:+5.2f}"
    print(line)
print("\n=== |Δ| 分位 (池化) ===")
for name,(aa,bb) in CAND.items():
    idx,v,dv=PO; ad=np.abs(dv-(aa*idx+bb)*v)
    print(f"  {name:26s} P25={np.percentile(ad,25):5.2f} P50={np.percentile(ad,50):5.2f} P75={np.percentile(ad,75):5.2f} P90={np.percentile(ad,90):6.2f} P99={np.percentile(ad,99):6.2f}")

print("\n=== 连续帧『反复横跳』复核 (rowsC 4 route) ===")
RC={}
for r in ('00000004','00000049','00000071','00000072'):
    p=f'/tmp/rowsC_{r}.npy'
    RC[r]=np.load(p) if os.path.exists(p) else np.zeros((0,10))
CONT=np.vstack([RC[r] for r in RC])
print(f"  rowsC 总帧 {len(CONT)}")
for name,(aa,bb) in CAND.items():
    tot=0; jit=[]; big5=0; big10=0; prev=None; flips=0; nprev=None; regimes=0; totreg=0
    for r,X in RC.items():
        if not len(X): continue
        idx,v,dv,vv,vc,zl=X[:,0],np.maximum(X[:,1],5.0),X[:,2],X[:,3],X[:,4],X[:,5]; seg=X[:,8]; k=X[:,9]
        ok=(v>=8.0)&(idx>=100)&(idx<=560)&(dv>0)
        d=(aa*idx+bb)*v
        rel=np.abs(dv-d)/np.maximum(d,1.0); mode=(rel>0.30).astype(int)
        for i in range(1,len(X)):
            if not(ok[i] and ok[i-1]): continue
            if seg[i]!=seg[i-1] or k[i]!=k[i-1]+1: continue
            dd=abs(d[i]-d[i-1]); jit.append(dd); tot+=1
            big5+=dd>5; big10+=dd>10
            if mode[i]!=mode[i-1]: flips+=1
    jit=np.array(jit)
    print(f"  {name:26s} 帧对={tot:7d} med|Δd|={np.median(jit):.3f}m P99={np.percentile(jit,99):.2f}m >5m={1000*big5/tot:.1f}‰ >10m={1000*big10/tot:.1f}‰ 模式翻转={1000*flips/tot:.1f}‰")
