#!/usr/bin/env python3
"""006c 猛刹车分析：定位596-745s的猛刹/猛加速事件与滞回/lead切换关联"""
import glob
from openpilot.tools.lib.logreader import LogReader

fs=sorted(glob.glob('/data/media/0/realdata/0000006c--79e4b58991--*/rlog.zst'), key=lambda f:int(f.split('--')[-1].split('/')[0]))
t0=None
for m in LogReader(fs[0]):
    if m.which() in ('can','carState'):
        t0=m.logMonoTime/1e9; break
print(f"route起点t0={t0:.1f}s 段数={len(fs)}")

def verz_of(d):
    raw=0
    for i in range(11):
        byte=(32+i)//8; bit=(32+i)%8
        if byte<len(d) and d[byte]&(1<<bit): raw|=1<<i
    return raw*0.005-7.22

last={}; rows=[]
for f in fs[10:14]:
    for m in LogReader(f):
        t=m.logMonoTime/1e9-t0
        if t>750 or t<594: continue
        w=m.which()
        if w=='carState': last['v']=float(m.carState.vEgo)
        elif w=='longitudinalPlan':
            last['at']=float(m.longitudinalPlan.aTarget)
            try: last['vc']=float(m.longitudinalPlan.vCruise)
            except Exception: pass
        elif w=='controlsState':
            try: last['acc']=float(m.controlsState.actuators.accel)
            except Exception: pass
        elif w=='radarState':
            ld=m.radarState.leadOne
            last['lp']=bool(ld.present); last['ld']=float(ld.dRel)
        elif w=='can':
            for c in m.can:
                if c.src==2 and c.address==269 and len(c.dat)>=8:
                    last['vz']=verz_of(c.dat); last['st']=(c.dat[7]>>1)&0x7
                elif c.src==2 and c.address==780 and len(c.dat)>=7:
                    last['idx']=(c.dat[3]|(c.dat[4]<<8))&0x3FF
        if w=='carState':
            rows.append((t,dict(last)))
print(f"采样点={len(rows)}")

def fmt(d):
    return (f"v={d.get('v',0):.1f} aT={d.get('at',0):.2f} aO={d.get('acc',0):.2f} "
            f"vC={d.get('vc',0):.0f} lead={'Y' if d.get('lp') else 'N'}{d.get('ld',0):.0f} "
            f"idx={d.get('idx','-')} vz={d.get('vz',0):.2f} st={d.get('st','-')}")

print("\n=== 每10s总览 ===")
prev10=None
for t,d in rows:
    if prev10 is None or t-prev10>=10:
        prev10=t
        print(f"{t:6.1f} {fmt(d)}")

print("\n=== 事件窗: aTarget<-1.2 或 >1.5 或 输出acc<-1.2 (前后±1.2s @0.25s) ===")
ev_win=[]
for i,(t,d) in enumerate(rows):
    at=d.get('at',0); ac=d.get('acc',0)
    if at<-1.2 or at>1.5 or ac<-1.2:
        ev_win.append((t,at,ac))
# 合并相邻事件为窗口
wins=[]
for t,at,ac in ev_win:
    if wins and t-wins[-1][1]<2.0:
        wins[-1][1]=t
    else:
        wins.append([t,t])
for w0,w1 in wins:
    print(f"\n--- 事件 {w0:.1f}s~{w1:.1f}s ---")
    for t,d in rows:
        if w0-1.2<=t<=w1+1.2 and abs((t*4)%1-0)<0.25 or (w0-1.2<=t<=w1+1.2 and int(t*4)%4==0):
            print(f"{t:6.1f} {fmt(d)}")
