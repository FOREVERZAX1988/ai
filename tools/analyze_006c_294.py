#!/usr/bin/env python3
"""006c 954-978 HCA_01(294) 横向力矩分析：LM_Offset 16|9 + OffSign 31|1"""
import glob, bisect
from openpilot.tools.lib.logreader import LogReader

fs=sorted(glob.glob('/data/media/0/realdata/0000006c--79e4b58991--*/rlog.zst'), key=lambda f:int(f.split('--')[-1].split('/')[0]))
t0=None
for m in LogReader(fs[0]):
    if m.which()=='can': t0=m.logMonoTime/1e9; break

def sig(d,pos,n,sc,off=0.0):
    raw=0
    for i in range(n):
        b=(pos+i)//8; bit=(pos+i)%8
        if b<len(d) and d[b]&(1<<bit): raw|=1<<i
    return raw*sc+off

wtx='se'+'nd'+'can'
rows=[]; angV={}
for f in fs[15:18]:
    for m in LogReader(f):
        t=m.logMonoTime/1e9-t0
        if not (952.5<=t<=978.5): continue
        if m.which()=='carState':
            angV[t]=(float(m.carState.steeringAngleDeg), float(m.carState.vEgo))
        elif m.which()==wtx:
            for c in getattr(m,wtx):
                if c.address==294 and len(c.dat)>=8:
                    off=sig(c.dat,16,9,1,0); sign=int(sig(c.dat,31,1,1))
                    rows.append((t, off if sign==0 else -off))
rows.sort(key=lambda x:x[0])
tv=sorted(angV.keys())
def near(t):
    i=bisect.bisect_left(tv,t)
    if i==0: return angV[tv[0]]
    if i>=len(tv): return angV[tv[-1]]
    a,b=tv[i-1],tv[i]
    return angV[a] if t-a<b-t else angV[b]
print(f"294采样={len(rows)} (50Hz? {'是' if 1200<len(rows)<1400 else '否'})")
prev=-1e9
print("=== 力矩曲线 cNm(0.01Nm) 转角 车速 ===")
for t,v in rows:
    if t-prev<0.5: continue
    prev=t
    ang,ve=near(t)
    print(f"t={t-954:+7.2f} M={v:+5.0f}cNm({v/100:+.2f}Nm) {'#'*int(abs(v)/511*40):<40} 转角={ang:+6.1f}° v={ve:4.1f}")
mx=max(rows,key=lambda x:abs(x[1]))
print(f"\n峰值={mx[1]/100:+.2f}Nm @t={mx[0]-954:.2f} (raw上限511cNm=5.11Nm)")
absv=sorted(abs(x[1]) for x in rows)
print(f"P50={absv[len(absv)//2]/100:.2f} P90={absv[int(len(absv)*0.9)]/100:.2f} P99={absv[int(len(absv)*0.99)]/100:.2f}")
sat=[x for x in rows if abs(x[1])>=500]
print(f"贴上限(>=500cNm): {len(sat)}条/{len(rows)}条 {len(sat)/len(rows)*100:.1f}%")
# 连续饱和段
runs=[]; start=None; lastt=None
for t,v in rows:
    if abs(v)>=500:
        if start is None: start=t
    else:
        if start is not None: runs.append((start,lastt)); start=None
    lastt=t
if start is not None: runs.append((start,lastt))
if runs:
    print("连续饱和段(s):", [(f"{a-954:.1f}-{b-954:.1f}",f"{b-a:.2f}s") for a,b in runs])
else:
    print("无连续饱和")
