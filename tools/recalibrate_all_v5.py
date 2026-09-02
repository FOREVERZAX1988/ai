#!/usr/bin/env python3
"""全量样本采集 v5（2026-09-02）——在v4基础上存 [idx, vEgo, t] 三元组
用途: 分速度策略诊断（按 v>10 / 5-10 / 2-5 分场景评估表格误差）
- 只取 bus2(src==2) 原厂 ACC_02 idx；视觉参照 modelV2.leadsV3[0]
- 条件: 0<idx<1021, prob>0.5, 2<d<300m, v_ego>2m/s; t=(d-1)/v
- 输出: ai/tools/fit_parts_v5/<route-seg>.json = [[idx, v, t], ...]
"""
import glob, json, os, multiprocessing as mp

ROUTES=["00000002","00000003","00000004","00000049","00000065","00000066"]
OUT='/data/openpilot/ai/tools/fit_parts_v5'

def scan_one(f):
  from openpilot.tools.lib.logreader import LogReader
  fn=os.path.join(OUT, os.path.basename(os.path.dirname(f))+'.json')
  if os.path.exists(fn): return ('skip', 0)
  cur_idx=0; cur_v=0.0; cur_prob=0.0; cur_d=None; samples=[]
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
          if len(ld)>0:
            cur_prob=float(ld[0].prob)
            cur_d=float(ld[0].x[0]) if len(ld[0].x)>0 else None
          else: cur_prob=0.0; cur_d=None
        except Exception: cur_prob=0.0; cur_d=None
        if 0<cur_idx<1021 and cur_prob>0.5 and cur_d and 2.0<cur_d<300.0 and cur_v>2.0:
          samples.append([cur_idx, round(cur_v,1), round((cur_d-1.0)/cur_v,3)])
  except Exception as e:
    print(f"ERR {os.path.basename(os.path.dirname(f))}: {e}", flush=True)
    return ('err', 0)
  try:
    json.dump(samples, open(fn,'w'))
  except Exception as e:
    print(f"WRITE_ERR {fn}: {e}", flush=True); return ('err',0)
  return ('ok', len(samples))

if __name__=='__main__':
  os.makedirs(OUT, exist_ok=True)
  fs=[]
  for r in ROUTES: fs+=sorted(glob.glob(f'/data/media/0/realdata/{r}--*--*/rlog.zst'))
  print(f"总段数={len(fs)}", flush=True)
  done=0; errs=0
  with mp.Pool(6) as p:
    for st,c in p.imap_unordered(scan_one, fs, chunksize=1):
      if st=='ok': done+=c
      elif st=='err': errs+=1
  print(f"采集样本={done} 错误段={errs} 文件数={len(os.listdir(OUT))}", flush=True)
  missing=[f for f in fs if not os.path.exists(os.path.join(OUT, os.path.basename(os.path.dirname(f))+'.json'))]
  for i,f in enumerate(missing):
    print(f"补采 {i+1}/{len(missing)}", flush=True)
    scan_one(f)
  print(f"补采后文件数={len(os.listdir(OUT))}", flush=True)
  print("v5采集完成", flush=True)
