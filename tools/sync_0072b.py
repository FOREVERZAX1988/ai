import os, glob
from openpilot.tools.lib.logreader import LogReader
base='/data/media/0/realdata/00000072--d7b307b456'
# focus on engaging segments with transitions
for segid in ['12','15','16','19','24','3']:
    seg=base+'-'+segid
    rlog=os.path.join(seg,'rlog.zst')
    lr=LogReader(rlog)
    t0=None; v_prev=None; last_vc=None; last_w=None
    events=[]
    # collect (t,vCruise) and (t,wunsch) and button events
    for m in lr:
        w=m.which()
        tm=m.logMonoTime/1e6
        if t0 is None: t0=tm
        t=tm-t0
        if w=='carState':
            v=m.carState.vCruise
            if v>0 and v<250:
                last_vc=(t,v)
            # button events
            for be in m.carState.buttonEvents:
                events.append(('BTN',round(t,2),be.type,be.pressed,last_vc[1] if last_vc else None))
        elif w=='can':
            for cf in m.can:
                if cf.address==0x30c and cf.src==2 and len(cf.dat)>=3:
                    d=cf.dat; raw=((d[1]>>4)&0x3)|(d[2]<<4); v=raw*0.32
                    if v<250:
                        last_w=(t,v)
    print(f'--- seg{segid}: buttons=', [e for e in events][:12])
