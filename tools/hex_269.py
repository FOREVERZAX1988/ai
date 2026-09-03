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
def b2(raw): return raw*0.01-1.28 if False else raw  # dat[2]原值
cnt=0
for f in fs[10:12]:
    for m in LogReader(f):
        t=m.logMonoTime/1e9-t0
        if not (599.5<=t<=608.5): continue
        w=m.which()
        if w==SC:
            for c in getattr(m, SC):
                if c.address==269 and len(c.dat)>=8:
                    h=bytes(c.dat).hex()
                    cnt+=1
                    if cnt<=26:
                        print(f"OP {t:6.2f} hex={h} verz={verz_of(c.dat):6.2f} d2={c.dat[2]:3d} st={(c.dat[7]>>1)&0x7}")
        elif w=='can':
            for c in m.can:
                if c.src==2 and c.address==269 and len(c.dat)>=8:
                    h=bytes(c.dat).hex()
                    cnt+=1
                    if cnt<=52:
                        print(f"ST {t:6.2f} hex={h} verz={verz_of(c.dat):6.2f} d2={c.dat[2]:3d} st={(c.dat[7]>>1)&0x7}")
