import os
from openpilot.tools.lib.logreader import LogReader
base='/data/media/0/realdata/00000072--d7b307b456'
def load(segid):
    seg=base+'-'+segid
    rlog=os.path.join(seg,'rlog.zst')
    lr=LogReader(rlog)
    t0=None; vc_list=[]; w_list=[]
    for m in lr:
        w=m.which()
        tm=m.logMonoTime/1e6
        if t0 is None: t0=tm
        t=tm-t0
        if w=='carState':
            v=m.carState.vCruise
            if 5<v<250: vc_list.append((t,round(v,1)))
        elif w=='can':
            for cf in m.can:
                if cf.address==0x30c and cf.src==2 and len(cf.dat)>=3:
                    d=cf.dat; raw=((d[1]>>4)&0x3)|(d[2]<<4); v=raw*0.32
                    if 5<v<250: w_list.append((t,round(v,1)))
    return vc_list, w_list
def edges(seq,thr=0.6):
    out=[]; last=None
    for t,v in seq:
        if last is None or abs(v-last[1])>thr:
            out.append((round(t,2),v))
            last=(t,v)
    return out
for segid in ['12','15','16','19','24','22','3']:
    vc,w=load(segid)
    if not vc: continue
    ve=edges(vc); we=edges(w)
    print(f'seg{segid}: vc_edges={ve[:6]}')
    print(f'          w_edges={we[:6]}')
