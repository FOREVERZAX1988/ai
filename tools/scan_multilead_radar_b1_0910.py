#!/usr/bin/env python3
"""多目标排查：当视觉 lead0 与雷达 B1 距离偏差较大时，检查视觉 lead1/lead2 是否更贴近雷达。
用法: cd /data/openpilot && python3 ai/tools/scan_multilead_radar_b1_0910.py [threshold=0.25] [max_segs=40]
数据: 仅取 bus2(src==2) 原厂信号: ACC_02 idx、ESP轮速、ACC_04 前车速度。
B1: d_rad=(0.008969*idx+0.332)*max(v,5)。"""
import sys, glob, os
sys.path.insert(0,'/data/openpilot/openpilot'); sys.path.insert(0,'/data/openpilot')
from openpilot.tools.lib.logreader import LogReader
import numpy as np
TH=float(sys.argv[1]) if len(sys.argv)>1 else 0.25
MAXSEG=int(sys.argv[2]) if len(sys.argv)>2 else 40
REAL="/data/media/0/realdata"; A,B=0.008969,0.332
def scan(seg,max_frames=25000):
    rows=[]; cur=dict(vw=0.0,idx=-1,vlead=np.nan); n=0
    for m in LogReader(f"{REAL}/{seg}/rlog.zst"):
        n+=1; w=m.which()
        if w=="can":
            for c in m.can:
                if c.src!=2: continue
                d=c.dat
                if c.address==780 and len(d)>=8: cur["idx"]=float((d[3]|(d[4]<<8))&0x3FF)
                elif c.address==259 and len(d)>=8:
                    s=(((d[2]|(d[3]<<8))&0xFFF)+(((d[3]>>4)|(d[4]<<4))&0xFFF)+((d[5]|(d[6]<<8))&0xFFF)+(((d[6]>>4)|(d[7]<<4))&0xFFF))*0.1
                    cur["vw"]=s/4/3.6
                elif c.address==804 and len(d)>=8:
                    v=((d[5]|(d[6]<<8))&0x3FF)*0.32; cur["vlead"]=np.nan if v>=320 else v/3.6
        elif w=="modelV2":
            ld=m.modelV2.leadsV3; dd=[np.nan]*3; pp=[0.0]*3; vv=[np.nan]*3
            for i in range(3):
                if i<len(ld) and len(ld[i].x)>0:
                    dd[i]=float(ld[i].x[0]); pp[i]=float(ld[i].prob)
                    vv[i]=float(ld[i].v[0]) if len(ld[i].v)>0 else np.nan
            if cur["idx"]>=0 and np.isfinite(cur["vlead"]) and cur["vw"]>8.0:
                t=A*cur["idx"]+B; d_rad=t*cur["vw"]
                if np.isfinite(dd[0]) and dd[0]>0 and d_rad>1:
                    rel=abs(dd[0]-d_rad)/d_rad
                    if rel>TH: rows.append((dd[0],d_rad,dd[1],dd[2],pp[0],pp[1],vv[0],vv[1],rel))
            cur["idx"]=-1; cur["vlead"]=np.nan
        if n>max_frames: break
    return rows
def main():
    routes=["00000002","00000003","00000004","00000049","00000071","00000072"]
    out={}
    for route in routes:
        segs=glob.glob(f"{REAL}/{route}--*/rlog.zst")[:MAXSEG]
        rr=[]
        for p in segs:
            seg=os.path.basename(os.path.dirname(p))
            try: rr+=scan(seg)
            except Exception: pass
        out[route]=rr
        print(f"\n=== {route}  rel>{TH} 帧 n={len(rr)} ===")
        if not rr: continue
        a=np.array(rr); d0=a[:,0]; dr=a[:,1]; d1=a[:,2]; d2=a[:,3]; p0=a[:,4]; p1=a[:,5]; v0=a[:,6]; v1=a[:,7]
        n1=np.isfinite(d1)&(d1>0); n2=np.isfinite(d2)&(d2>0)
        print(f"  lead0 vs雷达 med|Δ|={np.median(abs(d0-dr)):.1f}m radar={np.median(dr):.0f} lead0={np.median(d0):.0f} p0={np.median(p0):.2f}")
        print(f"  lead1 存在={100*n1.mean():.0f}% vs雷达 med|Δ|={np.median(abs(d1[n1]-dr[n1])):.1f}m p1={np.median(p1[n1]):.2f}" if n1.sum() else "  lead1 无样本")
        print(f"  lead2 存在={100*n2.mean():.0f}% vs雷达 med|Δ|={np.median(abs(d2[n2]-dr[n2])):.1f}m" if n2.sum() else "  lead2 无样本")
        if n1.sum()>30:
            better=(abs(d1-dr)<abs(d0-dr)-0.5)&n1
            print(f"  [lead1 比 lead0 更贴近雷达>0.5m] 占比={100*better.mean():.1f}%")
    # 汇总
    tot=sum(len(v) for v in out.values())
    print(f"\n=== 汇总: rel>{TH} 帧总数 = {tot} ===")
if __name__=="__main__": main()
