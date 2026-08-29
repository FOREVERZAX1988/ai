#!/usr/bin/env python3
"""vz_corr.py — verz 相关性/超前量分析（黑盒反推控制律输入）
对整段：verz 与 aEgo(滞后0~0.5s)/vRel/dRel 的相关性 + verz峰值时间超前 aEgo峰值
"""
import glob,os,sys,re
sys.path.insert(0,"/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
DBC="/data/openpilot/opendbc_repo/opendbc/dbc/vw_mlb.dbc"
BASE="/data/media/0/realdata"
def sigs():
    L=open(DBC,encoding="latin-1").read().splitlines()
    s=next(i for i,l in enumerate(L) if l.startswith('BO_ 269 '))
    e=next(i for i in range(s+1,len(L)) if L[i].startswith('BO_ '))
    out={}
    for l in "\n".join(L[s:e]).splitlines():
        m=re.match(r'^\s*SG_ (\w+) : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)',l)
        if m: out[m.group(1)]=(int(m.group(2)),int(m.group(3)),m.group(5)=='-',float(m.group(6)),float(m.group(7)))
    return out
def gs(d,sl,ln,sg,sc=1.0,of=0.0):
    if len(d)<=(sl+ln-1)//8: return 0
    v=0
    for i in range(ln):
        b=(sl+i)//8; bt=(sl+i)%8
        if d[b]&(1<<bt): v|=(1<<i)
    if sg and v&(1<<(ln-1)): v-=(1<<ln)
    return v*sc+of
import numpy as np
pref,segno=sys.argv[1],int(sys.argv[2])
p=glob.glob(f"{BASE}/{pref}--*--{segno}/rlog.zst")[0]
S=sigs()
T=[]; cs={}; rt=(None,None,None)
for m in LogReader(p):
    w=m.which()
    if w=='carState':
        c=m.carState; cs={'v':c.vEgo,'a':c.aEgo}
    elif w=='radarTracks':
        pts=m.radarTracks.points
        if len(pts): t0=pts[0]; rt=(t0.dRel,t0.vRel, getattr(t0.deprecated,'aRel',None))
    elif w=='can':
        for c in m.can:
            if c.address==269 and c.src==2 and len(c.dat)>=8:
                d=bytes(c.dat)
                vz=gs(d,*S['ACC_Verz_anf']); st=int(gs(d,*S['ACC_Status_ACC']))
                if st==3 and vz<0:
                    T.append((m.logMonoTime/1e9, cs.get('a',0), vz, rt[0] or 0, rt[1] or 0))
T.sort(key=lambda r:r[0])
if len(T)<20: print("减速样本不足:",len(T)); sys.exit()
A=np.array([r[1] for r in T]); V=np.array([r[2] for r in T])
D=np.array([r[3] for r in T]); VR=np.array([r[4] for r in T])
print(f"seg{segno} 减速样本 {len(T)} 帧")
print(f"verz范围 {V.min():.3f}~{V.max():.3f}, aEgo范围 {A.min():.3f}~{A.max():.3f}")
print(f"verz均值 {V.mean():.3f} vs aEgo均值 {A.mean():.3f} → verz≈{abs(V.mean()/max(abs(A.mean()),1e-9)):.2f}×aEgo(超前请求)")
# 相关性（verz vs 各输入同帧）
for name,X in [("aEgo",A),("dRel",D),("vRel",VR)]:
    if X.std()>0:
        c=np.corrcoef(V,X)[0,1]
        print(f"corr(verz,{name}) = {c:+.3f}")
# verz 与 aEgo 超前：verz领先k帧
for k in [5,10,20]:
    if len(V)>k:
        c=np.corrcoef(V[:-k],A[k:])[0,1]
        print(f"corr(verz[t], aEgo[t+{k*0.02:.1f}s]) = {c:+.3f}")
# 峰值超前：找verz最负点 vs 之后aEgo最负点
iv=int(np.argmin(V)); t_vz=T[iv][0]
win=[(i,r[1]) for i,r in enumerate(T) if 0<=(i-iv)<=50]
if win:
    ia=min(win,key=lambda x:x[1])[0]
    dt=(T[ia][0]-t_vz)
    print(f"verz峰值@t={t_vz%120:.1f}s, aEgo峰值@t={T[ia][0]%120:.1f}s → verz领先 {dt:.1f}s")
