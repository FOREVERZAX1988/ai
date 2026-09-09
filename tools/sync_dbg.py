import os, glob
from openpilot.tools.lib.logreader import LogReader
base='/data/media/0/realdata/00000072--d7b307b456'
seg=base+'-5'
lr=LogReader(os.path.join(seg,'rlog.zst'))
t0=None; n_vc=0; n_w=0
sample_vc=[]; sample_w=[]
for m in lr:
    ww=m.which(); tm=m.logMonoTime/1e6
    if t0 is None: t0=tm
    t=round(tm-t0,3)
    if ww=='carState':
        v=m.carState.vCruise
        if 5<v<250:
            n_vc+=1
            if len(sample_vc)<5: sample_vc.append((t,v))
    elif ww=='can':
        for cf in m.can:
            if cf.address==0x30c and cf.src==2 and len(cf.dat)>=3:
                d=cf.dat; raw=((d[1]>>4)&0x3)|(d[2]<<4); v=raw*0.32
                if 5<v<250:
                    n_w+=1
                    if len(sample_w)<5: sample_w.append((t,v))
print('vc count',n_vc,'sample',sample_vc)
print('w count',n_w,'sample',sample_w)
