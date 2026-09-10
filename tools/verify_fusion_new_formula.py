#!/usr/bin/env python3
"""# Verify fusion adaptation for new radar distance formula.
Compares radard fusion using OLD interpolation table vs NEW linear formula on
0004 high-speed segments. Decisive question: is switching fusion to the new
formula an optimization (better fusion accuracy, sane replacement rate)?
"""
import glob, statistics, sys
import numpy as np
from collections import defaultdict
from openpilot.tools.lib.logreader import LogReader

# 0004 high-speed segments (from REFIT_0909: seg19-26 reach 70-95km/h)
SEGS = ["19","20","21","22","23","24","25","26"]
OC_LOG = glob.glob('/data/media/0/realdata/00000004--*--'+n+'/rlog.zst' for n in SEGS)

# old table (from radard.py _macan_abstands_t/_idx)
OLD_T = [0.81,0.81,0.81,0.81,0.81,0.785,0.804,0.822,0.837,0.872,0.942,0.932,0.899,0.978,1.025,1.14,1.168,1.185,1.203,1.275,1.288,1.364,1.422,1.439,1.459,1.505,1.571,1.616,1.682,1.708,1.766,1.801,1.828,1.869,1.933,2.0,2.028,2.091,2.12,2.17,2.246,2.24,2.351,2.353,2.394,2.435,2.467,2.497,2.553,2.635,2.653,2.711,2.774,2.823,2.923,2.968,3.031,3.075,3.121,3.128,3.197,3.263,3.249,3.221,3.299,3.398,3.472,3.435,3.37,3.531,3.619,3.628,3.684,3.826,3.726,3.778,3.884,3.925,3.955,3.955,4.074,4.038,4.065,3.966,4.014,4.154,4.193,4.216,4.406,4.453,4.301,4.438,4.562,4.482,4.512,4.587,4.71,4.802,4.565,4.708,4.835,4.974,4.654,4.799,4.81,5.048,4.816,5.052,5.098,5.015,5.237,5.364,5.606,5.354,5.336,5.782,5.384,5.474,5.536,5.604,5.377,5.619,5.587,5.762,5.787,5.909,5.862,6.202,6.331,6.144,5.986,5.941,5.893,6.144,6.061,6.458,6.146,6.397,6.59,6.58,6.536,6.392,6.494,6.0,6.94,6.0,6.0,6.0,6.0,7.149,6.0,6.0,6.0]
OLD_IDX = [27,32,37,42,47,52,57,62,67,72,77,82,87,92,97,102,107,112,117,122,127,132,137,142,147,152,157,162,167,172,177,182,187,192,197,202,207,212,217,222,227,232,237,242,247,252,257,262,267,272,277,282,287,292,297,302,307,312,317,322,327,332,337,342,347,352,357,362,367,372,377,382,387,392,397,402,407,412,417,422,427,432,437,442,447,452,457,462,467,472,477,482,487,492,497,502,507,512,517,522,527,532,537,542,547,552,557,562,567,572,577,582,587,592,597,602,607,612,617,622,627,632,637,642,647,652,657,662,667,672,677,682,687,692,697,702,707,712,717,722,727,732,737,742,747,752,757,762,767,772,777,780,1021]

def old_idx_to_t(idx):
    idx=max(min(idx,1021),27)
    return float(np.interp(idx, OLD_IDX, OLD_T))

def new_idx_to_t(idx):
    # linear formula (b018e1dc)
    if idx < 100: return 0.8
    if idx > 560: return 6.0
    return 0.008718*idx + 1.0178

def collect():
    # (idx, v_ego, d_vis) where d_vis from model lead
    pairs=[]
    for seg in SEGS:
        g=glob.glob(f'/data/media/0/realdata/00000004--{seg}*/rlog.zst')
        if not g: 
            print(f'  seg{seg}: missing',flush=True); continue
        # 0004 uses flat rlogs at 00000004--hash--seg/rlog.zst? check both layouts
        g2=glob.glob(f'/data/media/0/realdata/00000004--{seg}/rlog.zst')
        g = g or g2
        f=g[0]
        cur_idx=0; cur_v=0.0
        try:
            for m in LogReader(f):
                w=m.which()
                if w=='can':
                    for c in m.can:
                        if c.src==2 and c.address==780 and len(c.dat)>=7:
                            cur_idx=(c.dat[3]|(c.dat[4]<<8))&0x3FF
                elif w=='carState':
                    cur_v=float(m.carState.vEgo)
                elif w=='modelV2':
                    ld=m.modelV2.leadsV3
                    if len(ld)==0 or len(ld[0].x)==0: continue
                    p=float(ld[0].prob); dv=float(ld[0].x[0])
                    if p<0.5 or not(0<cur_idx<1021) or cur_v<0.5: continue
                    pairs.append((cur_idx,cur_v,dv))
        except Exception as e:
            print(f'  seg{seg} err {e}',flush=True)
    return pairs

if __name__=='__main__':
    print('collecting 0004 high-speed pairs...',flush=True)
    s=collect()
    print(f'pairs={len(s)}',flush=True)
    if len(s)<500:
        print('insufficient samples'); sys.exit(1)
    idxs=np.array([x[0] for x in s]); vs=np.array([x[1] for x in s]); dvis=np.array([x[2] for x in s])
    # stock distance under old vs new
    d_old=np.array([old_idx_to_t(i) for i in idxs])*np.maximum(vs,5.0)
    d_new=np.array([new_idx_to_t(i) for i in idxs])*np.maximum(vs,5.0)
    # ratio metric used by A2: |vis_idx - stock_idx|/stock_idx
    # use idx-domain consistent with _macan_drel_to_idx (old table) vs new inverse
    def rel_err(d_stock):
        r=np.abs(dvis-d_stock)/d_stock
        return r
    for name,d in [('OLD_TABLE(当前radard)',d_old),('NEW_FORMULA(待适配)',d_new)]:
        r=rel_err(d)
        repl=np.mean(r>0.3)*100
        mix=np.mean(r<=0.3)*100
        print(f'\n[{name}]')
        print(f'  d_stock 中位={np.median(d):.1f}m  mean={np.mean(d):.1f}m')
        print(f'  fused dRel vs stock 中位 rel_err = {np.median(r)*100:.2f}%')
        print(f'  A2 "原厂替换"(ratio>30%) = {repl:.1f}%   70/30混合 = {mix:.1f}%')