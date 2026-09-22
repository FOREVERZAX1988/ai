import glob, sys, bisect
sys.path.insert(0,'/data/openpilot')
from openpilot.tools.lib.logreader import LogReader
BASE='/data/media/0/realdata'; PREFIX='0000007c'
SEGS=[4,6,8,12,5,10]
def scan(segfile):
    cur_idx=0.0;cur_v=0.0;cur_spd=0.0;idx_t={};vis=[]
    for m in LogReader(segfile):
        w=m.which()
        if w=='can':
            for c in m.can:
                if c.src==2 and c.address==780 and len(c.dat)>=7:
                    cur_idx=float((c.dat[3]|(c.dat[4]<<8))&0x3FF)
                elif c.src==2 and c.address==804 and len(c.dat)>=7:
                    v=((c.dat[5]|(c.dat[6]<<8))&0x3FF)*0.32
                    cur_spd=v if v<320 else 0.0
        elif w=='carState': cur_v=float(m.carState.vEgo)
        elif w=='modelV2':
            mt=m.logMonoTime; idx_t[mt]=(cur_idx,cur_v,cur_spd)
            ld=m.modelV2.leadsV3
            if len(ld)>0 and len(ld[0].x)>0: vis.append((mt,float(ld[0].x[0]),float(ld[0].prob)))
    times=sorted(idx_t); rows=[]
    for mt,vd,p in vis:
        j=bisect.bisect_right(times,mt)-1
        if j<0: continue
        idx,v,spd=idx_t[times[j]]
        rows.append((mt,idx,v,vd,p,spd))
    return rows
def main():
    rows=[]
    for seg in SEGS:
        for f in sorted(glob.glob(f'{BASE}/{PREFIX}--*--{seg}/rlog.zst')): rows+=scan(f)
    rows.sort(key=lambda r:r[0])
    # 打印 t=396-420s (停车段含 idx翻转) 的帧
    for r in rows:
        t=r[0]/1e9
        if 396<t<421:
            print(f"t={t:.2f} idx={r[1]:.0f} vEgo={r[2]:.1f} dVis={r[3]:.1f} prob={r[4]:.2f} spd={r[5]:.0f}kmh")
main()
