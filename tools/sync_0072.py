import os, glob
from openpilot.tools.lib.logreader import LogReader
base='/data/media/0/realdata/00000072--d7b307b456'
segs=sorted(glob.glob(base+'-*'))
out=[]
for seg in segs:
    rlog=os.path.join(seg,'rlog.zst')
    if not os.path.exists(rlog): continue
    try:
        lr=LogReader(rlog)
    except Exception as e:
        out.append((os.path.basename(seg),'ERR',str(e))); continue
    t0=None; vc=None; v_prev=None; w_vals=set(); v_vals=set(); transits=[]
    for m in lr:
        w=m.which()
        tm=m.logMonoTime/1e6
        if t0 is None: t0=tm
        t=tm-t0
        if w=='carState':
            v=m.carState.vCruise
            if v>0:
                key=round(v,1); v_vals.add(key)
                if v_prev is not None and abs(v_prev-key)>0.51:
                    transits.append(('vc',round(t,1),v_prev,key))
                v_prev=key
        elif w=='can':
            for cf in m.can:
                if cf.address==0x30c and cf.src==2 and len(cf.dat)>=3:
                    d=cf.dat; raw=((d[1]>>4)&0x3)|(d[2]<<4); v=raw*0.32
                    if v<250: w_vals.add(round(v,1))
    nm=os.path.basename(seg)
    out.append((nm,'OK',sorted(v_vals)[:8],sorted(w_vals)[:8],transits[:8]))
for o in out:
    print(o)
