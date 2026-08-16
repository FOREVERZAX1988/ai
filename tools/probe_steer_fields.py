#!/usr/bin/env python3
"""调试：seg1 的对齐与过滤问题。"""
import sys
sys.path.insert(0, '/data/openpilot')
from openpilot.tools.lib.logreader import LogReader

path = '/data/media/0/realdata/00000047--3ee0e0227b--1/rlog.zst'
lr = LogReader(path)

t0 = None
frames = {}
ctl_count = 0
aligned = 0
for msg in lr:
  w = msg.which()
  if t0 is None:
    t0 = msg.logMonoTime
  t = (msg.logMonoTime - t0) / 1e9
  if w == 'carState':
    cs = msg.carState
    frames[t] = {'v': cs.vEgo, 'dA': None, 'err': None, 'out': None}
  elif w == 'controlsState':
    ctl_count += 1
    try:
      ts = msg.controlsState.lateralControlState.torqueState
      best = min(frames, key=lambda k: abs(k - t), default=None)
      if best is not None and abs(best - t) < 0.1:
        frames[best]['dA'] = ts.desiredLateralAccel
        frames[best]['err'] = ts.error
        frames[best]['out'] = ts.output
        aligned += 1
    except Exception as e:
      print('ERR', e)
  if t > 59:
    break

print(f"carState 帧: {len(frames)} | controlsState: {ctl_count} | 对齐成功: {aligned}")
moving_dA = [(t, f) for t, f in sorted(frames.items()) if f['v'] > 10/3.6 and f['dA'] is not None]
print(f"行驶且dA非None: {len(moving_dA)}")
if moving_dA:
  print("前5个样本:", [(round(t,2), round(f['v'],1), round(f['dA'],2), round(f['err'],3), round(f['out'],3)) for t, f in moving_dA[:5]])
  mx = max(moving_dA, key=lambda x: abs(x[1]['dA']))
  print(f"最大dA: {mx[1]['dA']:.2f} @t={mx[0]:.1f}s v={mx[1]['v']*3.6:.0f}km/h err={mx[1]['err']:.3f} out={mx[1]['out']:.3f}")
