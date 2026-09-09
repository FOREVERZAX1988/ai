#!/usr/bin/env python3
"""#1 融合权重标定（2026-09-04）：按距离分段求 A1/A2 最优视觉权重
数据: modelV2.leadsV3[0](纯视觉 d/v) + can(原厂 ACC_02 idx -> t -> d_stock=t*v_ego)
方法: 按原厂距离 d_stock 分段, 每段网格搜索 w∈[0,1] 使 |fused - d_stock| 最小
      fused = w*vision + (1-w)*stock  (w=视觉权重)
      同时输出该段视觉系统偏差(均值/中位) 供判断视觉偏近/偏远
用法: python3 ai/tools/calibrate_fusion_weight.py
"""
import glob, os, statistics
from collections import defaultdict
import numpy as np

# 用最近路试 routes（含起步/跟车场景）
ROUTES = ["00000070--ecfb4e987f--28","00000070--ecfb4e987f--27",
          "00000070--ecfb4e987f--26","00000070--ecfb4e987f--25",
          "00000070--ecfb4e987f--24"]
# idx->t 表（与 radard.py 一致, 从 v6 结果读）
V6 = '/data/openpilot/ai/tools/fit_all_v6_result.json'
import json
IDX=[]; T=[]
if os.path.exists(V6):
  d=json.load(open(V6))
  IDX=d.get('idx',d.get('IDX',[])); T=d.get('t',d.get('T',[]))
def idx_to_t(idx):
  if not IDX: return None
  return float(np.interp(idx, IDX, T))

def collect():
  samp=[]  # (d_stock, d_vis, v_vis, v_ego)
  for r in ROUTES:
    f=f'/data/media/0/realdata/{r}/rlog.zst'
    if not os.path.exists(f): continue
    from openpilot.tools.lib.logreader import LogReader
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
          p=float(ld[0].prob); dv=float(ld[0].x[0]); vv=float(ld[0].v[0])
          if p<0.5 or not(0<cur_idx<1021) or cur_v<0.5: continue
          t=idx_to_t(cur_idx)
          if t is None: continue
          d_stock=t*cur_v
          if 2.0<d_stock<200 and 2.0<dv<300:
            samp.append((d_stock,dv,vv,cur_v))
    except Exception as e:
      print(f'{r} err {e}')
  return samp

if __name__=='__main__':
  print('采集样本...', flush=True)
  s=collect()
  print(f'总样本={len(s)}', flush=True)
  if len(s)<50:
    print('样本不足，无法标定'); raise SystemExit
  # 距离分段
  edges=[0,10,20,35,55,80,120,300]
  print(f'\n{"段(m)":>10} {"n":>5} {"视觉偏(m)":>9} {"最优w":>6} {"融合RMSE":>8} {"纯原厂RMSE":>9}')
  results={}
  for i in range(len(edges)-1):
    lo,hi=edges[i],edges[i+1]
    seg=[x for x in s if lo<=x[0]<hi]
    if len(seg)<20: continue
    ds=np.array([x[0] for x in seg]); dv=np.array([x[1] for x in seg])
    bias=float(np.median(dv-ds))  # 视觉-原厂
    # 网格搜索最优 w
    best_w,best_e=0.0,1e9
    for w in np.arange(0,1.01,0.05):
      f=w*dv+(1-w)*ds
      e=float(np.sqrt(np.mean((f-ds)**2)))
      if e<best_e: best_e,best_w=e,w
    stock_e=float(np.sqrt(np.mean((ds-ds)**2)))  # 原厂自身=0基准
    # 视觉单独RMSE 作参考
    vis_e=float(np.sqrt(np.mean((dv-ds)**2)))
    results[f'{lo}-{hi}']={'n':len(seg),'bias':round(bias,2),'w':round(best_w,2),'vis_rmse':round(vis_e,2)}
    print(f'{lo:>4}-{hi:<5} {len(seg):>5} {bias:>+8.2f} {best_w:>6.2f} {best_e:>8.2f} {vis_e:>9.2f}')
  json.dump(results, open('/data/openpilot/ai/tools/fusion_weight_result.json','w'), indent=2)
  print('\n已存 fusion_weight_result.json')
