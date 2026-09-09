import os, glob, statistics
from openpilot.tools.lib.logreader import LogReader
base='/data/media/0/realdata/00000072--d7b307b456'
def load(rlog):
    lr=LogReader(rlog)
    t0=None; vc=[]; w=[]
    for m in lr:
        ww=m.which(); tm=m.logMonoTime/1e6
        if t0 is None: t0=tm
        t=round(tm-t0,3)
        if ww=='carState':
            v=m.carState.vCruise
            if 5<v<250: vc.append((t,round(v,1)))
        elif ww=='can':
            for cf in m.can:
                if cf.address==0x30c and cf.src==2 and len(cf.dat)>=3:
                    d=cf.dat; raw=((d[1]>>4)&0x3)|(d[2]<<4); v=raw*0.32
                    if 5<v<250: w.append((t,round(v,1)))
    return vc,w
for seg in sorted(glob.glob(base+'-*')):
    rlog=os.path.join(seg,'rlog.zst')
    if not os.path.exists(rlog): continue
    try: vc,w=load(rlog)
    except Exception as e:
        print(os.path.basename(seg),'ERR',e); continue
    if len(vc)<10 or len(w)<10: continue
    # align via nearest time match
    import bisect
    wt=[x[0] for x in w]; wv=[x[1] for x in w]
    diffs=[]
    for t,v in vc:
        i=bisect.bisect_left(wt,t)
        if i<len(wt) and abs(wt[i]-t)<0.05:
            diffs.append(v-wv[i])
    if len(diffs)<10: continue
    print(f'{os.path.basename(seg)}: n={len(diffs)} off={statistics.mean(diffs):5.1f} sd={statistics.pstdev(diffs):4.1f}')
