#!/usr/bin/env python3
"""v6全量重标定（2026-09-02）：prob≥0.9 高置信度过滤版
背景: 快速实验显示 prob≥0.9 使分箱CV 0.24→0.18(-25%)，idx460-479等被低prob帧拉偏(15%)
v6 = v4流程 + prob≥0.9 + 正确留出(每route段号最大2段, int排序)
继承基准=v4表(153点)——差异纯粹来自prob过滤
输出: fit_all_v6_result.json + 留出验证(v4vs v6) + 表值差异>3%逐点列表
用法: python3 ai/tools/recalibrate_all_v6.py
"""
import glob, json, os, statistics, multiprocessing as mp
from collections import defaultdict
import numpy as np

ROUTES=["00000002","00000003","00000004","00000049","00000065","00000066"]
OUT='/data/openpilot/ai/tools/fit_parts_v6'
V4=json.load(open('/data/openpilot/ai/tools/fit_all_v4_result.json'))
V4_IDX=V4['idx']; V4_T=V4['t']
def v4_t(idx): return float(np.interp(idx, V4_IDX, V4_T))

def scan_one(f):
  from openpilot.tools.lib.logreader import LogReader
  fn=os.path.join(OUT, os.path.basename(os.path.dirname(f))+'.json')
  if os.path.exists(fn): return 'skip'
  cur_idx=0; cur_v=0.0; samples=[]
  try:
    for m in LogReader(f):
      w=m.which()
      if w=='can':
        for c in m.can:
          if c.src!=2 or c.address!=780 or len(c.dat)<7: continue
          cur_idx=(c.dat[3]|(c.dat[4]<<8))&0x3FF
      elif w=='carState':
        cur_v=float(m.carState.vEgo)
      elif w=='modelV2':
        try:
          ld=m.modelV2.leadsV3
          if len(ld)==0 or len(ld[0].x)==0: continue
          p=float(ld[0].prob); d=float(ld[0].x[0])
        except Exception: continue
        if p>=0.9 and 0<cur_idx<1021 and 2.0<d<300.0 and cur_v>2.0:
          t=(d-1.0)/cur_v
          if 0<t<20: samples.append([cur_idx, round(cur_v,1), round(t,3)])
  except Exception: return 'err'
  try:
    json.dump(samples, open(fn,'w'))
  except Exception: return 'err'
  return 'ok'

if __name__=='__main__':
  os.makedirs(OUT, exist_ok=True)
  fs=[]
  for r in ROUTES: fs+=sorted(glob.glob(f'/data/media/0/realdata/{r}--*--*/rlog.zst'))
  print(f"总段数={len(fs)}", flush=True)
  with mp.Pool(6) as p:
    for st in p.imap_unordered(scan_one, fs, chunksize=1): pass
  print("采集完成", flush=True)
  fit=[]; val=[]
  for r in ROUTES:
    files=[f for f in os.listdir(OUT) if f.startswith(r+'--') and f.endswith('.json')]
    def segnum(f): return int(f.split('--')[-1].replace('.json',''))
    files_sorted=sorted(files, key=segnum)
    for f in files_sorted[:-2]: fit.extend(json.load(open(os.path.join(OUT,f))))
    for f in files_sorted[-2:]: val.extend(json.load(open(os.path.join(OUT,f))))
  print(f"拟合={len(fit)} 验证={len(val)}", flush=True)
  bins=defaultdict(list)
  for idx,v,t in fit: bins[idx//5].append(t)
  pts={}
  for b in sorted(bins):
    ts=bins[b]
    pts[b*5+2]=statistics.median(ts) if len(ts)>=30 else v4_t(b*5+2)
  IDX=sorted([x for x in pts if x<780])+[780,1021]
  T=[pts[x] for x in IDX[:-2]]+[v4_t(780), v4_t(780)]
  def ev(idx_arr,t_arr,data):
    errs=defaultdict(list)
    for idx,v,t in data:
      p=float(np.interp(idx,idx_arr,t_arr)); e=abs(p-t)/t
      errs['all'].append(e)
      errs['lo' if idx<234 else 'mid' if idx<420 else 'hi' if idx<780 else 'xhi'].append(e)
    return {k:(len(v), float(np.median(v)*100) if v else float('nan')) for k,v in errs.items()}
  print("\n=== 留出验证: v4 vs v6 ===")
  cur=ev(V4_IDX,V4_T,val); new=ev(IDX,T,val)
  for k in ['lo','mid','hi','xhi','all']:
    print(f"{k:<5} n={cur[k][0]:>5}  v4={cur[k][1]:6.2f}%  v6={new[k][1]:6.2f}%  改善={cur[k][1]-new[k][1]:+.2f}pp", flush=True)
  print("\n=== v6 vs v4 表值差异 >3% ===")
  for i,idx in enumerate(IDX):
    if idx>=780: continue
    t4=float(np.interp(idx, V4_IDX, V4_T))
    if t4<=0: continue
    diff=abs(T[i]-t4)/t4*100
    if diff>3: print(f"  idx{idx:>4}: v4={t4:.3f}s -> v6={T[i]:.3f}s ({(T[i]-t4)/t4*100:+.1f}%)")
  json.dump({'fit_n':len(fit),'val_n':len(val),'idx':IDX,'t':[round(x,3) for x in T]},
            open('/data/openpilot/ai/tools/fit_all_v6_result.json','w'))
  print("\n=== v6表代码 ===")
  print(f"self._macan_abstands_idx = {IDX}")
  print(f"self._macan_abstands_t = {[round(x,3) for x in T]}")
  print("DONE", flush=True)
