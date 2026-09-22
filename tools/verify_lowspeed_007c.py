import glob, sys, bisect
sys.path.insert(0,'/data/openpilot')
from openpilot.tools.lib.logreader import LogReader
TA,TB=0.008969,0.332
BASE='/data/media/0/realdata'; PREFIX='0000007c'
SEGS=[4,6,8,12,5,10]
def d_from_idx(i,v): return (TA*i+TB)*max(v,5.0)
def scan(segfile):
    cur_idx=0.0;cur_v=0.0;idx_t={};vis=[]
    for m in LogReader(segfile):
        w=m.which()
        if w=='can':
            for c in m.can:
                if c.src==2 and c.address==780 and len(c.dat)>=7:
                    cur_idx=float((c.dat[3]|(c.dat[4]<<8))&0x3FF)
        elif w=='carState': cur_v=float(m.carState.vEgo)
        elif w=='modelV2':
            idx_t[m.logMonoTime]=(cur_idx,cur_v)
            ld=m.modelV2.leadsV3
            if len(ld)>0 and len(ld[0].x)>0: vis.append((m.logMonoTime,float(ld[0].x[0]),float(ld[0].prob)))
    times=sorted(idx_t); rows=[]
    for mt,vd,p in vis:
        j=bisect.bisect_right(times,mt)-1
        if j<0: continue
        idx,v=idx_t[times[j]]
        if idx<=0 or idx>=1021: continue
        ds=d_from_idx(idx,v)
        rows.append((mt,idx,v,ds,vd))
    return rows
def main():
    rows=[]
    for seg in SEGS:
        for f in sorted(glob.glob(f'{BASE}/{PREFIX}--*--{seg}/rlog.zst')): rows+=scan(f)
    rows.sort(key=lambda r:r[0])
    # 低速(v<=5)段 idx有效帧的 d_stock 分布 vs 视觉
    slow=[r for r in rows if r[2]<=5.0]
    print(f"idx有效帧总 {len(rows)} | 低速(v<=5) {len(slow)}")
    if slow:
        import statistics as st
        ds=[r[3] for r in slow]; dv=[r[4] for r in slow]
        print(f"低速 idx有效帧 d_stock: min {min(ds):.1f} med {st.median(ds):.1f} max {max(ds):.1f}  大值(>20m)占比 {sum(1 for d in ds if d>20)/len(ds)*100:.0f}%")
        print(f"低速 idx有效帧 d_vis : min {min(dv):.1f} med {st.median(dv):.1f} max {max(dv):.1f}")
        # blend 后 (A2 rel>0.3 全替换)
        big=[(r[0],r[1],r[2],r[3],r[4]) for r in slow if r[3]>20 and r[4]<r[3]*0.7]
        print(f"  其中 d_stock>20m 且 视觉<70%: {len(big)} 帧")
        for b in big[:8]:
            print(f"    t={b[0]/1e9:.1f}s idx={b[1]:.0f} v={b[2]:.0f} d_stock={b[3]:.1f}m d_vis={b[4]:.1f}m")
main()
