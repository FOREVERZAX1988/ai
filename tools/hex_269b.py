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
import collections
st_seq=collections.defaultdict(list)
op_seq=collections.defaultdict(list)
for f in fs[10:12]:
    for m in LogReader(f):
        t=m.logMonoTime/1e9-t0
        if not (601.5<=t<=608.5): continue
        w=m.which()
        if w==SC:
            for c in getattr(m, SC):
                if c.address==269 and len(c.dat)>=8:
                    op_seq[int(t*5)].append((verz_of(c.dat), c.dat[2], (c.dat[7]>>1)&0x7))
        elif w=='can':
            for c in m.can:
                if c.src==2 and c.address==269 and len(c.dat)>=8:
                    st_seq[int(t*5)].append((verz_of(c.dat), c.dat[2], (c.dat[7]>>1)&0x7))
for tick in sorted(set(st_seq)|set(op_seq)):
    t=tick/5
    s=st_seq.get(tick,[]); o=op_seq.get(tick,[])
    if not s or not o: continue
    sv=sum(x[0] for x in s)/len(s); sm=sum(x[1] for x in s)/len(s); sst=s[0][2]
    ov=sum(x[0] for x in o)/len(o); om=sum(x[1] for x in o)/len(o); ost=o[0][2]
    mark='←切换' if (sv<0 and om>100) or (ov<0 and sm>100) else ''
    print(f"{t:6.2f} ST: verz={sv:6.2f} mom={sm:4.0f} st={sst} | OP: verz={ov:6.2f} mom={om:4.0f} st={ost} {mark}")
