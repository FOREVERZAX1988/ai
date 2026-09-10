#!/usr/bin/env python3
"""全 route 扫描：逐帧对比 d_vis(视觉) vs d_old(旧153表) vs d_new(新线性)，union 统计。
d_stock = t(idx) * max(v_ego,5)。报告绝对量一致性，跨 route 泛化检查。"""
import sys, json, os, glob
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/openpilot")
import numpy as np
from openpilot.tools.lib.logreader import LogReader

IDX_TAB=np.array(json.load(open('/data/openpilot/ai/tools/abstands_idx_table.json')))
T_TAB=np.array(json.load(open('/data/openpilot/ai/tools/abstands_t_table.json')))
def t_old(idx): return float(np.interp(idx,IDX_TAB,T_TAB))
def t_new(idx):
    if idx<100: return 0.8
    if idx>560: return 6.0
    return 0.008718*idx+1.0178

def parse(f):
    rows=[]; cur_idx=0.0; cur_vwh=0.0; vis_d=None; vis_p=0.0; cur_zl=0
    for m in LogReader(f):
        w=m.which()
        if w=='can':
            for c in m.can:
                if c.address==259 and len(c.dat)>=8:
                    d=c.dat
                    s=(((d[2]|(d[3]<<8))&0xFFF)+(((d[3]>>4)|(d[4]<<4))&0xFFF)+((d[5]|(d[6]<<8))&0xFFF)+(((d[6]>>4)|(d[7]<<4))&0xFFF))*0.1
                    cur_vwh=s/4/3.6
                elif c.src==2 and c.address==780 and len(c.dat)>=7:
                    cur_idx=float((c.dat[3]|(c.dat[4]<<8))&0x3FF)
                    cur_zl=int((c.dat[4]>>5)&7)
        elif w=='modelV2':
            ld=m.modelV2.leadsV3
            if len(ld)>0 and len(ld[0].x)>0:
                vis_p=float(ld[0].prob); vis_d=float(ld[0].x[0])
        elif w=='carState':
            ve=float(m.carState.vEgo); vuse=cur_vwh if cur_vwh>1.0 else ve
            if vis_d is not None and vis_p>0.5 and cur_idx>10 and vuse>1.0:
                rows.append((cur_idx,vuse,vis_d,cur_zl))
    return rows

def stats(route, rows):
    idx=np.array([r[0] for r in rows]); v=np.array([r[1] for r in rows]); dv=np.array([r[2] for r in rows]); zl=np.array([r[3] for r in rows])
    dold=np.array([t_old(i) for i in idx])*np.maximum(v,5.0)
    dnew=np.array([t_new(i) for i in idx])*np.maximum(v,5.0)
    n=len(rows)
    np.savez(f'/data/openpilot/ai/tools/.scan/{route}.npz', idx=idx, v=v, dvis=dv, zl=zl)
    e_old=dv-dold; e_new=dv-dnew
    return dict(route=route,n=n,
        vmed=np.median(v)*3.6, idxmed=np.median(idx),
        dv=np.median(dv), dold=np.median(dold), dnew=np.median(dnew),
        e_old=np.median(e_old), e_new=np.median(e_new),
        w5_old=np.mean(np.abs(e_old)<=5)*100, w5_new=np.mean(np.abs(e_new)<=5)*100,
        rep_old=np.mean(np.abs(e_old)/np.maximum(dold,1)>0.30)*100,
        rep_new=np.mean(np.abs(e_new)/np.maximum(dnew,1)>0.30)*100)

if __name__=='__main__':
    routes={}
    for f in sorted(glob.glob('/data/media/0/realdata/*--*/rlog.zst')):
        rt=f.split('/')[-2].split('--')[0]
        routes.setdefault(rt,[]).append(f)
    want=set(sys.argv[1:])
    out=[]
    for rt in sorted(routes):
        if want and rt not in want: continue
        allrows=[]
        for f in sorted(routes[rt]):
            allrows.extend(parse(f))
        if len(allrows)<200: 
            print(f'{rt}: n={len(allrows)} 跳过'); continue
        s=stats(rt,allrows); out.append(s)
    print(f"\n{'route':>9} {'n':>7} {'v(km/h)':>7} {'idx':>6} | {'d_vis':>6} {'d_old':>6} {'d_new':>6} | {'vis-old':>7} {'vis-new':>8} | {'%≤5m old':>9} {'new':>5} | {'替换% old':>8} {'new':>5}")
    for s in out:
        print(f"{s['route']:>9} {s['n']:>7} {s['vmed']:>7.1f} {s['idxmed']:>6.0f} | {s['dv']:>6.1f} {s['dold']:>6.1f} {s['dnew']:>6.1f} | {s['e_old']:>+7.1f} {s['e_new']:>+8.1f} | {s['w5_old']:>9.1f} {s['w5_new']:>5.1f} | {s['rep_old']:>8.1f} {s['rep_new']:>5.1f}")
