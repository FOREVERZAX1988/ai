import os, glob
from openpilot.tools.lib.logreader import LogReader
base='/data/media/0/realdata/00000072--d7b307b456'
def edges(seq,thr=0.6):
    out=[]; last=None
    for t,v in seq:
        if last is None or abs(v-last[1])>thr:
            out.append((round(t,2),v)); last=(t,v)
    return out
for seg in sorted(glob.glob(base+'-*')):
    rlog=os.path.join(seg,'rlog.zst')
    if not os.path.exists(rlog): continue
    try: lr=LogReader(rlog)
    except Exception: continue
    t0=None; vc=[]; w=[]
    for m in lr:
        ww=m.which(); tm=m.logMonoTime/1e6
        if t0 is None: t0=tm
        t=tm-t0
        if ww=='carState':
            v=m.carState.vCruise
            if 5<v<250: vc.append((t,round(v,1)))
        elif ww=='can':
            for cf in m.can:
                if cf.address==0x30c and cf.src==2 and len(cf.dat)>=3:
                    d=cf.dat; raw=((d[1]>>4)&0x3)|(d[2]<<4); v=raw*0.32
                    if 5<v<250: w.append((t,round(v,1)))
    if len(vc)<5 or len(w)<5: continue
    ve=edges(vc); we=edges(w)
    segid=os.path.basename(seg)
    print(f'{segid}: vc={ve[:5]}  w={we[:5]}')
