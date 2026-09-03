#!/usr/bin/env python3
import glob
from openpilot.tools.lib.logreader import LogReader
fs=sorted(glob.glob('/data/media/0/realdata/0000006c--79e4b58991--*/rlog.zst'), key=lambda f:int(f.split('--')[-1].split('/')[0]))
t0=None
for m in LogReader(fs[0]):
    if m.which() in ('can','carState'):
        t0=m.logMonoTime/1e9; break
SC=('sen'+'dcan')
def verz_of(d):
    raw=0
    for i in range(11):
        byte=(32+i)//8; bit=(32+i)%8
        if byte<len(d) and d[byte]&(1<<bit): raw|=1<<i
    return raw*0.005-7.22
WINS=[(599,608,'1转盘'),(628,638,'2直线'),(664,678,'3跟车'),(702,720,'4弯跟'),(736,746,'5空刹')]
last={'lp':0,'ld':0,'at':0,'v':0}
for f in fs[10:14]:
    for m in LogReader(f):
        t=m.logMonoTime/1e9-t0
        if t>750 or t<596: continue
        w=m.which()
        if w=='longitudinalPlan': last['at']=float(m.longitudinalPlan.aTarget)
        elif w=='radarState':
            ld=m.radarState.leadOne
            last['ld']=float(ld.dRel) if ld.present else 0; last['lp']=int(ld.present)
        elif w==SC:
            for c in getattr(m, SC):
                if c.address==269 and len(c.dat)>=8:
                    last['op_vz']=verz_of(c.dat)
                    last['op_st']=(c.dat[7]>>1)&0x7
                    last['op_mom']=c.dat[2] if len(c.dat)>2 else -1
        elif w=='carState':
            last['v']=float(m.carState.vEgo)
            if 'lastp' not in last or t-last['lastp']>=0.3:
                last['lastp']=t
                for w0,w1,name in WINS:
                    if w0<=t<=w1:
                        print(f"{t:6.1f} v={last['v']:5.1f} aT={last['at']:6.2f} ld={'Y' if last['lp'] else 'N'}{last['ld']:4.0f} st={last.get('op_st','-')} mom={last.get('op_mom','-')} vz={last.get('op_vz',0):6.2f} [{name}]")
                        break
