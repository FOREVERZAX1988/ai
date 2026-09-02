#!/usr/bin/env python3
"""运动学尺子校验（2026-09-02）：视觉距离 vs 轮速+雷达速度积分的差分一致性
原理: 前车匀速巡航窗内, 真实距离变化= -∫(v_ego - v_lead)dt (v_lead=ACC_04雷达测前车绝对速度)
      d_vis = scale×d_true + offset → 回归 d_vis ~ -Δs 的 slope≈scale
结果(738窗): 有效窗125个 slope中位0.975(≈1) 残差2.3% → 视觉无系统性比例偏差
用法: python3 ai/tools/kinematic_scan.py [段目录...]（默认扫描 realdata 全部段的采样）
"""
import os, glob
import numpy as np
from openpilot.tools.lib.logreader import LogReader

def scan_seg(segdir, wins, W=80, step=8):
  f = segdir + '/rlog.zst'
  if not os.path.exists(f): return
  mt=[]; md=[]; mp=[]; ct=[]; cv=[]; rt=[]; rv=[]
  for m in LogReader(f):
    w=m.which()
    if w=='carState':
      ct.append(m.logMonoTime); cv.append(m.carState.vEgo)
    elif w=='modelV2':
      try:
        ld=m.modelV2.leadsV3
        if len(ld)>0 and len(ld[0].x)>0:
          mt.append(m.logMonoTime); md.append(ld[0].x[0]); mp.append(ld[0].prob)
      except Exception: pass
    elif w=='can':
      for c in m.can:
        if c.src==2 and c.address==804 and len(c.dat)>=7:
          spd=((c.dat[5]|(c.dat[6]<<8))&0x3FF)*0.32/3.6
          if 0<spd<45: rt.append(m.logMonoTime); rv.append(spd)
  if len(mt)<150 or len(rt)<150: return
  mt=np.array(mt)/1e9; ct=np.array(ct)/1e9; rt=np.array(rt)/1e9
  md=np.array(md); mp=np.array(mp)
  cv_i=np.interp(mt,ct,cv); rv_i=np.interp(mt,rt,rv)
  N=len(mt)
  for st in range(0,N-W,step):
    sl=slice(st,st+W); ok=mp[sl]>0.5
    if ok.sum()<W*0.7: continue
    vlead=rv_i[sl][ok]; d=md[sl][ok]; t=mt[sl][ok]
    if vlead.mean()<4 or np.std(vlead)>0.8: continue
    vrel=cv_i[sl][ok]-vlead
    ds=np.cumsum(vrel*np.concatenate([[0],np.diff(t)]))
    if np.ptp(ds)<3 or np.ptp(d)<4: continue
    A=np.column_stack([-ds,np.ones_like(ds)])
    coef,_,_,_=np.linalg.lstsq(A,d,rcond=None)
    med=np.median(np.abs(A@coef-d)/d)
    wins.append((os.path.basename(segdir).split('--')[0], float(coef[0]), float(med)))

if __name__=='__main__':
  import sys
  segs=sys.argv[1:] if len(sys.argv)>1 else sorted(glob.glob('/data/media/0/realdata/0*--*'))[:30]
  allw=[]
  for s in segs:
    try: scan_seg(s, allw)
    except Exception as e: print(f"{s}: ERR {e}", flush=True)
    print(f"{os.path.basename(s)}: 累计{len(allw)}窗", flush=True)
  if not allw: print("无窗口"); sys.exit(0)
  slopes=np.array([x[1] for x in allw])
  good=[x for x in allw if 0.85<x[1]<1.15]
  print(f"\n总窗口={len(allw)} 全部slope中位={np.median(slopes):.3f}")
  print(f"有效窗={len(good)} slope中位={np.median([x[1] for x in good]):.3f} 残差中位={np.median([x[2] for x in good])*100:.2f}%")
  print("scale≈1 → 视觉无系统比例偏差；≈1.1+ → 有 scale 病需真值修正")
