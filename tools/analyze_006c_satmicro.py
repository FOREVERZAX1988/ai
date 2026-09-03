#!/usr/bin/env python3
"""饱和段微观分析: +10.5~15.5s 0.1s采样 力矩/转角/v/曲率 —— 看转角是否平滑连续(无滞后停顿)"""
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
torq={}; state={}
for f in fs[15:18]:
    for m in LogReader(f):
        t=m.logMonoTime/1e9-t0
        if not (950.5<=t<=977.5): continue
        w=m.which()
        if w=='carState':
            cs=m.carState
            state.setdefault(t,{})['ang']=float(cs.steeringAngleDeg)
            state.setdefault(t,{})['v']=float(cs.vEgo)

        elif w=='carControl':
            cc=m.carControl
            try: state.setdefault(t,{})['curv']=float(cc.currentCurvature)
            except Exception: pass
        elif w==wtx:
            for c in getattr(m,wtx):
                if c.address==294 and len(c.dat)>=8:
                    off=sig(c.dat,16,9,1,0); sign=int(sig(c.dat,31,1,1))
                    torq[t]=off if sign==0 else -off
ts=sorted(set(list(torq.keys())+list(state.keys())))
def near(dd,t):
    tv=sorted(dd.keys())
    i=bisect.bisect_left(tv,t)
    if i==0: return dd[tv[0]]
    if i>=len(tv): return dd[tv[-1]]
    a,b=tv[i-1],tv[i]
    return dd[a] if t-a<b-t else dd[b]
print("=== +10.5~15.5s @0.1s: 力矩(饱和=-300) 转角 转角变化率 v ===")
prev=None
for i in range(105,156):
    t=954+i/10
    m=near(torq,t); s=near(state,t)
    ang=s.get('ang',0); v=s.get('v',0)
    dangle = (ang-prev) if prev is not None else 0
    prev=ang
    bar='#'*min(60,int(abs(m)/300*50))
    flag=' <<<饱和' if abs(m)>=295 else (' <<<接近' if abs(m)>=240 else '')
    print(f"t=+{t-954:5.1f} M={m:+4.0f} {bar:<52} 转角={ang:+6.1f}° Δ={dangle:+5.1f}°/0.1s v={v:4.1f}{flag}")
