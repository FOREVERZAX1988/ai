#!/usr/bin/env python3
"""分速度场景精度报告（2026-09-02）
用途: 诊断标定表在不同车速/idx区间的真实误差——决定是否/如何做分速度策略
输入: ai/tools/fit_parts_v5/*.json = [[idx, vEgo(m/s), t(s)], ...]（recalibrate_all_v5.py产出）
      表格: ai/tools/fit_all_v4_result.json
输出: 速度×idx区间 的 样本数/表格误差中位数%/idx时距稳定性CV%
误差定义: |表格预测t - 视觉参照t| / 视觉参照t —— 注意这是"表vs视觉"一致度,
        视觉是唯一参照尺(无独立真值), 低速误差大含"视觉尺子本身在低速不准"的成分
"""
import glob, json, os
import numpy as np

def main():
  res=json.load(open('/data/openpilot/ai/tools/fit_all_v4_result.json'))
  tbl_idx=np.array(res['idx']); tbl_t=np.array(res['t'])
  files=sorted(glob.glob('/data/openpilot/ai/tools/fit_parts_v5/*.json'))
  S=[]
  for f in files:
    try: S+=json.load(open(f))
    except Exception: pass
  S=np.array(S)  # [idx, v, t]
  print(f"样本总数={len(S)}  (idx范围[{S[:,0].min():.0f}-{S[:,0].max():.0f}], v范围[{S[:,1].min():.1f}-{S[:,1].max():.1f}])")
  speeds=[('高速 v>10', S[:,1]>10.0), ('中速 5-10', (S[:,1]>=5.0)&(S[:,1]<=10.0)), ('低速 2-5', (S[:,1]>=2.0)&(S[:,1]<5.0))]
  idx_ranges=[('idx<100', S[:,0]<100), ('100-234', (S[:,0]>=100)&(S[:,0]<234)), ('234-420', (S[:,0]>=234)&(S[:,0]<420)), ('420-780', (S[:,0]>=420)&(S[:,0]<780)), ('>780', S[:,0]>=780)]
  print(f"\n{'速度场景':<10} {'idx区间':<10} {'n':>6} {'表误差中位%':>10} {'带符号%':>8} {'t的CV%':>8}")
  for sn,sm in speeds:
    for iname,im in idx_ranges:
      m=sm&im
      n=m.sum()
      if n==0:
        print(f"{sn:<10} {iname:<10} {0:>6}    -        -       -"); continue
      idx,v,t=S[m,0],S[m,1],S[m,2]
      pred=np.interp(idx, tbl_idx, tbl_t)
      rel=np.abs(pred-t)/t
      sgn=np.median((pred-t)/t)*100
      med=np.median(rel)*100
      cv=np.std(t)/np.mean(t)*100
      print(f"{sn:<10} {iname:<10} {n:>6} {med:>9.1f}% {sgn:>7.1f}% {cv:>7.1f}%")
  print("\n注: 带符号%=正→表格预测>视觉(表偏大); 负→表偏小; CV%=同idx下时距离散度(>30%表示idx语义在该场景不稳)")

if __name__=='__main__':
  main()
