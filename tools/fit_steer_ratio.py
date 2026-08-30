#!/usr/bin/env python3
"""Macan 动态转向比（steerRatioV2）重新拟合
从设备 realdata 现有 routes 统计不同车速段的等效转向比（SR=方向盘转角/车轮转角，
自行车模型 wheel_angle=atan(yawRate*L/v)），验证 interface.py 的
steerRatioV2=[0,140,145,200,15,15,18.7,18.7] 是否仍成立。
用法:
  python3 fit_steer_ratio.py                     # qlog 全量扫描（快）
  python3 fit_steer_ratio.py --rlog --route 0000004f   # 指定前缀用 rlog
  python3 fit_steer_ratio.py --max-segs 6        # 每前缀最多 6 段
  python3 fit_steer_ratio.py --min-v 4 --min-yaw 0.01 --min-swa 2  # 滤波可调
"""
import argparse, os
import numpy as np
from collections import defaultdict

WHEELBASE = 2.81  # m
BUCKETS = [(0, 36), (36, 72), (72, 108), (108, 144), (144, 200)]

def main():
  ap = argparse.ArgumentParser()
  ap.add_argument('--mode', default='qlog', choices=['qlog', 'rlog'])
  ap.add_argument('--route', default=None, help='只扫指定 route 前缀(如 0000004f)')
  ap.add_argument('--max-segs', type=int, default=0, help='每前缀最多段数(0=全部)')
  ap.add_argument('--min-v', type=float, default=4.0, help='最小车速 m/s')
  ap.add_argument('--min-yaw', type=float, default=0.01, help='最小|yawRate| rad/s')
  ap.add_argument('--min-swa', type=float, default=2.0, help='最小|方向盘转角| deg')
  args = ap.parse_args()
  from openpilot.tools.lib.logreader import LogReader

  realdata = '/data/media/0/realdata'
  prefixes = sorted({d.split('--')[0] for d in os.listdir(realdata) if '--' in d and d.split('--')[0].isdigit()})
  if args.route:
    prefixes = [p for p in prefixes if p.startswith(args.route)]
  segs = []
  for p in prefixes:
    segs_p = sorted([d for d in os.listdir(realdata) if d.startswith(p + '--')])
    if args.max_segs > 0 and len(segs_p) > args.max_segs:
      idx = np.linspace(0, len(segs_p) - 1, args.max_segs).astype(int)
      segs_p = [segs_p[i] for i in idx]
    for s in segs_p:
      f = os.path.join(realdata, s, args.mode + '.zst')
      if os.path.exists(f):
        segs.append(f)
  print(f'扫描 {len(segs)} 段 {args.mode}（{len(prefixes)} 前缀）', flush=True)

  sr_all = defaultdict(list)
  per_route = defaultdict(lambda: defaultdict(lambda: [0, 0.0]))
  n_total = 0
  for i, f in enumerate(segs):
    rname = os.path.basename(os.path.dirname(f)).split('--')[0]
    try:
      for m in LogReader(f):
        if m.which() != 'carState':
          continue
        cs = m.carState
        v = cs.vEgo
        yaw = cs.yawRate
        swa = cs.steeringAngleDeg
        if v < args.min_v or abs(yaw) < args.min_yaw or abs(swa) < args.min_swa:
          continue
        wheel = np.arctan2(yaw * WHEELBASE, v)
        if abs(wheel) < 0.002:
          continue
        sr = abs(swa) / np.degrees(abs(wheel))
        if sr < 5 or sr > 40:
          continue
        vkmh = v * 3.6
        b = next((b for b in BUCKETS if b[0] <= vkmh < b[1]), None)
        if b is None:
          continue
        sr_all[b].append(sr)
        per_route[rname][b][0] += 1
        per_route[rname][b][1] += sr
        n_total += 1
    except Exception as e:
      print(f'  [跳过] {rname}: {e}', flush=True)
    if (i + 1) % 30 == 0:
      print(f'  ... {i+1}/{len(segs)} 段, 样本 {n_total}', flush=True)

  print(f'\n=== 全量拟合结果（有效样本 {n_total}）===')
  print(f'{"车速(km/h)":<16}{"n":>8}{"median":>8}{"mean":>8}{"std":>7}   {"现有V2参数"}')
  for b in BUCKETS:
    a = np.array(sr_all[b])
    cur = '15.0' if b[0] < 140 else ('过渡15.0→18.7' if b[0] < 145 else '18.7')
    if len(a):
      print(f'{b[0]:<4}-{b[1]:<9}{len(a):>8}{np.median(a):>8.2f}{a.mean():>8.2f}{a.std():>7.2f}   {cur}')
    else:
      print(f'{b[0]:<4}-{b[1]:<9}{0:>8}{"-":>8}{"-":>8}{"-":>7}   {cur}')
  print('\n=== 各 route 贡献（n(均值)）===')
  for r, bs in sorted(per_route.items()):
    parts = []
    for b in BUCKETS:
      n, s = bs[b]
      parts.append(f'{b[0]}-{b[1]}:{n}' + (f'({s/n:.1f})' if n else ''))
    print(f'  {r}: ' + ' | '.join(parts))

if __name__ == '__main__':
  main()
