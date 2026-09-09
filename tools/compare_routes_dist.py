#!/usr/bin/env python3
"""对比两条路线的融合距离稳定性。用法: python3 compare_routes_dist.py <routeA> <routeB> <labelA> <labelB>"""
import sys, json, os, glob
import numpy as np
from collections import defaultdict

VERBOSE = os.environ.get('VERBOSE')=='1'
ROUTE_A = sys.argv[1] if len(sys.argv)>1 else "00000071--363798636e"
ROUTE_B = sys.argv[2] if len(sys.argv)>2 else "00000070--ecfb4e987f"
LABEL_A = sys.argv[3] if len(sys.argv)>3 else "新版分段(0071)"
LABEL_B = sys.argv[4] if len(sys.argv)>4 else "旧版70/30(0070)"
BASE='/data/media/0/realdata'
T=json.load(open('/data/openpilot/ai/tools/abstands_t_table.json'))
X=json.load(open('/data/openpilot/ai/tools/abstands_idx_table.json'))
def idx_to_t(idx):
    if not X: return None
    return float(np.interp(idx, X, T))

def analyze(prefix, label):
    # 列出该 route 的所有 seg 目录
    segs = [f'{BASE}/{d}/rlog.zst' for d in os.listdir(BASE)
            if d.startswith(prefix) and os.path.isfile(f'{BASE}/{d}/rlog.zst')]
    segs.sort()
    print(f'\n===== {label} ({len(segs)} segs) =====', flush=True)
    from openpilot.tools.lib.logreader import LogReader
    bins = defaultdict(list)
    def add(seg,k,v): bins[(seg,k)].append(v)
    cur_idx=0; cur_v=0.0; last_ts=None; dprev=None; tprev=None
    jump=[]
    for f in segs:
        try:
            for m in LogReader(f):
                w=m.which()
                if w=='can':
                    for c in m.can:
                        if c.src==2 and c.address==780 and len(c.dat)>=7:
                            cur_idx=(c.dat[3]|(c.dat[4]<<8))&0x3FF
                elif w=='carState':
                    cur_v=float(m.carState.vEgo); last_ts=m.logMonoTime
                elif w=='modelV2':
                    ld=m.modelV2.leadsV3
                    if len(ld)==0 or len(ld[0].x)==0: continue
                    p=float(ld[0].prob); dv=float(ld[0].x[0])
                    if p<0.5 or not(0<cur_idx<1021) or cur_v<0.5: continue
                    t=idx_to_t(cur_idx)
                    if t is None: continue
                    d_stock=t*cur_v
                    if not(6.0<d_stock<150): continue
                    seg='5-15' if d_stock<15 else ('15-40' if d_stock<40 else ('40-60' if d_stock<60 else '60+'))
                    add(seg,'n',1); add(seg,'diff',dv-d_stock)
                    if dprev is not None: jump.append(abs(d_stock-dprev))
                    dprev=d_stock; tprev=last_ts
        except Exception as e:
            if VERBOSE: print(f'  {f} err {e}')
    print(f'{"距离段":<8}{"样本数":<8}{"偏差均值m":<11}{"偏差std":<9}')
    for seg in ['5-15','15-40','40-60','60+']:
        n=bins.get((seg,'n'),[])
        cnt=len(bins.get((seg,'diff'),[]))
        if not n: print(f'{seg:<8}0'); continue
        b=np.mean(bins[(seg,'diff')]); bs=np.std(bins[(seg,'diff')]) if cnt>1 else 0
        print(f'{seg:<8}{cnt:<8}{b:+.2f}m   {bs:.2f}m')
    if jump:
        print(f'  [融合距离|跳变|] 均值{np.mean(jump):.2f} p95{np.percentile(jump,95):.2f} p99{np.percentile(jump,99):.2f} max{max(jump):.2f}', flush=True)

if __name__=='__main__':
    analyze(ROUTE_A, LABEL_A)
    analyze(ROUTE_B, LABEL_B)
