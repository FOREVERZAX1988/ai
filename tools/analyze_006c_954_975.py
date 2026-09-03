#!/usr/bin/env python3
"""006c 954-975s 窗口分析（用户点播）：原厂269(st/mom/verz/FV/FM/loes/anh/axG) + OP侧(aT/aO/v/vC/lead)"""
import glob
from openpilot.tools.lib.logreader import LogReader

fs=sorted(glob.glob('/data/media/0/realdata/0000006c--79e4b58991--*/rlog.zst'), key=lambda f:int(f.split('--')[-1].split('/')[0]))
t0=None
for m in LogReader(fs[0]):
    if m.which()=='can':
        t0=m.logMonoTime/1e9; break
print(f"seg数={len(fs)} seg15={fs[15].split('/')[-2]} seg16={fs[16].split('/')[-2]}")

def sig(d,pos,n,sc,off=0.0):
    raw=0
    for i in range(n):
        byte=(pos+i)//8; bit=(pos+i)%8
        if byte<len(d) and d[byte]&(1<<bit): raw|=1<<i
    return raw*sc+off

last={}; rows=[]; st_src={}
for f in fs[15:18]:
    for m in LogReader(f):
        t=m.logMonoTime/1e9-t0
        if t>988 or t<940: continue
        w=m.which()
        if w=='carState':
            last['v']=float(m.carState.vEgo)
            last['aE']=float(m.carState.aEgo)
        elif w=='longitudinalPlan':
            last['at']=float(m.longitudinalPlan.aTarget)
            try: last['vc']=float(m.longitudinalPlan.vCruise)
            except Exception: pass
        elif w=='controlsState':
            try: last['ao']=float(m.controlsState.actuators.accel)
            except Exception: pass
        elif w=='radarState':
            ld=m.radarState.leadOne
            last['lp']=bool(ld.present); last['ld']=float(ld.dRel); last['lv']=float(ld.vRel)
        elif w=='can':
            for c in m.can:
                if c.address==269 and len(c.dat)>=8:
                    key=c.src
                    st_src.setdefault(key,0); st_src[key]+=1
                    if c.src==2:  # 原厂ACC发
                        last['st']=sig(c.dat,57,3,1); last['mom']=sig(c.dat,16,10,1)
                        last['vz']=sig(c.dat,32,11,0.005,-7.22)
                        last['fv']=sig(c.dat,13,1,1); last['fm']=sig(c.dat,12,1,1)
                        last['loes']=sig(c.dat,43,1,1); last['anh']=sig(c.dat,62,1,1)
                        last['axg']=sig(c.dat,48,9,0.024,-2.016)
                    elif c.src==0:
                        last['op269']=True; last['opst']=sig(c.dat,57,3,1)
        if w=='carState':
            rows.append((t,dict(last)))
rows.sort(key=lambda x:x[0])
print(f"269帧src分布: {st_src} 采样点={len(rows)}")

def fmt(d):
    return (f"v={d.get('v',0):5.1f} aE={d.get('aE',0):+5.2f} aT={d.get('at',0):+5.2f} aO={d.get('ao',0):+5.2f} "
            f"vC={d.get('vc',0):3.0f} lead={'Y' if d.get('lp') else '.'}{d.get('ld',0):3.0f}/{d.get('lv',0):+4.1f} "
            f"|269: st={d.get('st',0):.0f} mom={d.get('mom',0):3.0f} vz={d.get('vz',0):+5.2f} "
            f"FV={d.get('fv',0):.0f} FM={d.get('fm',0):.0f} loes={d.get('loes',0):.0f} anh={d.get('anh',0):.0f} axG={d.get('axg',0):+4.2f}")

print("\n=== 940-988s 总览 @0.5s ===")
prev=None
for t,d in rows:
    if prev is None or t-prev>=0.5:
        prev=t
        print(f"{t-954:7.2f} {fmt(d)}")
