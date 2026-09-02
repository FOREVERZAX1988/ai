#!/usr/bin/env python3
"""全量标定 v2（2026-09-02）
- 数据源: 本机全部 routes (00000002/03/04/49/65/66) 全部段
- 只取 bus2(原厂 ACC) 的 ACC_02 idx —— src!=2 一律跳过（bus128=OP代发, 严禁入标定）
- 视觉参照: modelV2.leadsV3[0] (prob>0.5, 2<d<300m, v_ego>2m/s), t=(d-1)/v
- 留出验证: 每 route 最后 2 段
- 拟合: 分箱宽5, n>=30 实测中位数, n<30 继承当前42点表插值
- 组合: 全部箱(到780)实测 + 780钳制原表6.0 + 1021尾点
- 输出: 区间验证(当前42点表 vs 新表) + 新表代码
"""
import glob, statistics, json
from collections import defaultdict
import numpy as np
from openpilot.tools.lib.logreader import LogReader

ROUTES=["00000002","00000003","00000004","00000049","00000065","00000066"]
# 当前42点表（radar_interface.py / radard.py 同源）
OLD_IDX=[62,67,72,77,82,87,92,97,102,107,112,117,122,127,132,137,142,147,152,157,162,167,172,177,182,187,192,197,202,207,212,217,222,227,232,234,271,363,380,389,401,420]
OLD_T=[0.810,0.787,0.938,0.980,0.893,0.903,1.027,1.086,1.171,1.192,1.279,1.375,1.550,1.433,1.428,1.442,1.501,1.511,1.626,1.702,1.686,1.806,1.807,1.925,1.939,1.802,1.928,2.149,2.168,2.073,2.182,2.236,2.411,2.462,2.584,2.000,2.500,3.000,3.500,4.000,4.500,6.000]
def old_t(idx): return float(np.interp(idx, OLD_IDX, OLD_T))

def scan(segs, fit_out, val_out):
  for si,f in enumerate(segs):
    cur_idx=0; cur_v=0.0; cur_prob=0.0; cur_d=None
    for m in LogReader(f):
      w=m.which()
      if w=='can':
        for c in m.can:
          if c.src!=2 or c.address!=780 or len(c.dat)<7: continue   # 只取 bus2 原厂
          cur_idx=(c.dat[3]|(c.dat[4]<<8))&0x3FF
      elif w=='carState':
        cur_v=float(m.carState.vEgo)
      elif w=='modelV2':
        try:
          ld=m.modelV2.leadsV3
          if len(ld)>0:
            cur_prob=float(ld[0].prob)
            cur_d=float(ld[0].x[0]) if len(ld[0].x)>0 else None
          else: cur_prob=0.0; cur_d=None
        except Exception: cur_prob=0.0; cur_d=None
        if 0<cur_idx<1021 and cur_prob>0.5 and cur_d and 2.0<cur_d<300.0 and cur_v>2.0:
          (val_out if si>=len(segs)-2 else fit_out).append((cur_idx,(cur_d-1.0)/cur_v))
    print(f"  seg{si} 完成", flush=True)

fit=[]; val=[]
for r in ROUTES:
  fs=sorted(glob.glob(f'/data/media/0/realdata/{r}--*--*/rlog.zst'))
  print(f"[{r}] 段数={len(fs)}", flush=True)
  scan(fs, fit, val)
print(f"\n拟合样本={len(fit)} 验证样本={len(val)}", flush=True)

# 分箱拟合（宽5, 箱中心=idx//5*5+2）
bins=defaultdict(list)
for idx,t in fit: bins[idx//5].append(t)
pts={}
for b in sorted(bins):
  ts=bins[b]
  if len(ts)>=30: pts[b*5+2]=statistics.median(ts)
  else: pts[b*5+2]=old_t(b*5+2)
IDX=sorted([x for x in pts if x<780])+[780,1021]
T=[pts[x] for x in IDX[:-2]]+[old_t(780), old_t(780)]

def ev(idx_arr,t_arr,data):
  errs=defaultdict(list)
  for idx,t in data:
    p=float(np.interp(idx, idx_arr, t_arr)); e=abs(p-t)/t
    errs['all'].append(e)
    errs['lo' if idx<234 else 'mid' if idx<420 else 'hi' if idx<780 else 'xhi'].append(e)
  return {k:(len(v), float(np.median(v)*100) if v else float('nan')) for k,v in errs.items()}

print("\n=== 留出验证：相对误差中位数% ===")
print(f"{'区间':<5} {'n(验证)':>8} {'当前42点表':>12} {'新表':>10}")
cur=ev(OLD_IDX,OLD_T,val); new=ev(IDX,T,val)
for k in ['lo','mid','hi','xhi','all']:
  print(f"{k:<5} {cur[k][0]:>8} {cur[k][1]:>10.2f}% {new[k][1]:>8.2f}%")

with open('/data/openpilot/ai/tools/fit_all_v2_result.json','w') as fh:
  json.dump({'fit_n':len(fit),'val_n':len(val),'idx':IDX,'t':[round(x,3) for x in T]}, fh, indent=1)

print("\n=== 新表代码 ===")
print(f"self._macan_abstands_idx = {IDX}")
print(f"self._macan_abstands_t = {[round(x,3) for x in T]}")
