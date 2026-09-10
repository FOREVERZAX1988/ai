#!/usr/bin/env python3
"""统一口径逐帧落盘（bus2 原厂 idx + 原厂前车速有效 + 视觉 lead 有效），供跨分支对比。
rows: [idx, v_use, d_vis, v_vis, v_can, zl, d_old, d_new]
用法: python3 dump_rows_bus2.py STRIDE ROUTE1 [ROUTE2 ...]
"""
import sys, os, json, numpy as np
sys.path.insert(0,"/data/openpilot"); sys.path.insert(0,"/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader
BASE='/data/media/0/realdata'
IDX=np.array(json.load(open('/data/openpilot/ai/tools/abstands_idx_table.json')))
TT=np.array(json.load(open('/data/openpilot/ai/tools/abstands_t_table.json')))
def t_old(i): return float(np.interp(i,IDX,TT))
def t_new(i): return 0.8 if i<100 else (6.0 if i>560 else 0.008718*i+1.0178)
STRIDE=int(sys.argv[1]); prefixes=sys.argv[2:]
for pre in prefixes:
    allsegs=sorted(d for d in os.listdir(BASE)
                   if d.startswith(pre) and os.path.isfile(f'{BASE}/{d}/rlog.zst'))
    segs=allsegs[::STRIDE]
    rows=[]; used=0
    for seg in segs:
        f=f'{BASE}/{seg}/rlog.zst'
        ci=0.0; czl=0; cl=-1.0; vwh=0.0; visd=None; visv=0.0; pr=0.0
        try:
            for m in LogReader(f):
                w=m.which()
                if w=='can':
                    for c in m.can:
                        if c.address==259 and len(c.dat)>=8:
                            d=c.dat
                            s=(((d[2]|(d[3]<<8))&0xFFF)+(((d[3]>>4)|(d[4]<<4))&0xFFF)
                               +((d[5]|(d[6]<<8))&0xFFF)+(((d[6]>>4)|(d[7]<<4))&0xFFF))*0.1
                            vwh=s/4*0.2778
                        elif c.src==2 and c.address==780 and len(c.dat)>=7:
                            ci=float((c.dat[3]|(c.dat[4]<<8))&0x3FF); czl=int((c.dat[4]>>5)&7)
                        elif c.src==2 and c.address==804 and len(c.dat)>=7:
                            v=((c.dat[5]|(c.dat[6]<<8))&0x3FF)*0.32
                            if v<320: cl=v
                elif w=='modelV2':
                    ld=m.modelV2.leadsV3
                    if len(ld)>0 and len(ld[0].x)>0:
                        pr=float(ld[0].prob); visd=float(ld[0].x[0])
                        visv=float(ld[0].v[0]) if len(ld[0].v)>0 else 0.0
                elif w=='carState':
                    ve=float(m.carState.vEgo); vuse=vwh if vwh>1.0 else ve
                    if visd is not None and pr>0.5 and 10<ci<1020 and vuse>5.0 and 0<cl<320:
                        rows.append([ci,vuse,visd,visv,cl/3.6,float(czl),t_old(ci)*max(vuse,5),t_new(ci)*max(vuse,5)])
            used+=1
        except Exception as e:
            print(f'  [warn] {seg}: {e}',file=sys.stderr)
    a=np.array(rows) if rows else np.zeros((0,8))
    np.save(f'/tmp/rows_{pre}.npy',a)
    print(f'{pre}: segs={len(segs)}/{len(allsegs)} (stride={STRIDE}) used={used} rows={len(rows)}',flush=True)
print('DONE',flush=True)
