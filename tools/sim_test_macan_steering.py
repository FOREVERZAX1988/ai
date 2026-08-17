#!/usr/bin/env python3
"""Macan 转向仿真测试 v7：线性对齐+全段扫描（性能优化）。

用法：python3 ai/tools/sim_test_macan_steering.py [route_prefix] [max_segments]
"""
import sys
import statistics

sys.path.insert(0, '/data/openpilot')
from openpilot.tools.lib.logreader import LogReader

ROUTE_PREFIX = sys.argv[1] if len(sys.argv) > 1 else '00000047--3ee0e0227b'
MAX_SEG = int(sys.argv[2]) if len(sys.argv) > 2 else 33
V_MIN = 10.0 / 3.6
SAT_RATIO = 0.9
UNDER_THRESHOLD = 0.3
CURVE_THRESHOLD = 1.0


def scan_segment(seg):
  """返回 [(t_sec, v, angle, pressed, dA, aA, err, out, sat)]"""
  path = f'/data/media/0/realdata/{ROUTE_PREFIX}--{seg}/rlog.zst'
  try:
    lr = LogReader(path)
  except Exception:
    return []

  car_frames = []   # (mono, v, angle, pressed)
  ctl_frames = []   # (mono, dA, aA, err, out, sat)
  for msg in lr:
    w = msg.which()
    if w == 'carState':
      cs = msg.carState
      car_frames.append((msg.logMonoTime, cs.vEgo, cs.steeringAngleDeg, bool(cs.steeringPressed)))
    elif w == 'controlsState':
      try:
        ts = msg.controlsState.lateralControlState.torqueState
        ctl_frames.append((msg.logMonoTime, ts.desiredLateralAccel, ts.actualLateralAccel,
                           ts.error, ts.output, ts.saturated))
      except Exception:
        pass

  if not car_frames:
    return []
  t0 = car_frames[0][0]

  # 双游标对齐
  out = []
  ci = 0
  for mono, v, angle, pressed in car_frames:
    dA = aA = err = out_ = sat = None
    # 前进到最近 ctl
    while ci < len(ctl_frames) and ctl_frames[ci][0] < mono:
      ci += 1
    best = None
    if ci < len(ctl_frames):
      best = ctl_frames[ci]
    if ci > 0 and abs(ctl_frames[ci-1][0] - mono) < (abs(best[0] - mono) if best else 1e18):
      best = ctl_frames[ci-1]
    if best is not None and abs(best[0] - mono) < 5e8:  # 0.5s
      _, dA, aA, err, out_, sat = best
    out.append(((mono - t0) / 1e9, v, angle, pressed, dA, aA, err, out_, sat))
  return out


def main():
  curves = []
  for seg in range(MAX_SEG):
    rows = scan_segment(seg)
    if not rows:
      continue
    # 提取行驶中且 dA 有值的帧
    moving = [(t, v, angle, pressed, dA, aA, err, out_, sat)
              for t, v, angle, pressed, dA, aA, err, out_, sat in rows
              if v >= V_MIN and dA is not None]
    cur = None
    for item in moving:
      t, v, angle, pressed, dA, aA, err, out_, sat = item
      is_curve = abs(dA) > CURVE_THRESHOLD
      if is_curve and cur is None:
        cur = {'seg': seg, 't0': t, 'rows': []}
      if cur is not None:
        cur['rows'].append(item)
        if not is_curve or (t - cur['t0']) > 45:
          cur['t1'] = t
          cur['dur'] = t - cur['t0']
          curves.append(cur)
          cur = None
    if cur:
      cur['t1'] = cur['rows'][-1][0]
      cur['dur'] = cur['t1'] - cur['t0']
      curves.append(cur)

  print(f"弯道片段总数: {len(curves)}\n")
  print(f"{'seg':>3} {'t0':>6} {'dur':>5} {'dAmax':>6} {'aAmax':>6} {'avg_err':>7} {'max_err':>7} {'不足帧':>5} {'饱和帧':>5} {'vmax':>5} {'介入':>3}")
  details = []
  for r in curves:
    rows = r['rows']
    if len(rows) < 8:
      continue
    abs_err = [abs(f[6]) for f in rows]
    outs = [f[7] for f in rows if f[7] is not None]
    sat = sum(1 for o in outs if abs(o) > SAT_RATIO)
    under = sum(1 for f in rows if f[6] is not None and f[6] > UNDER_THRESHOLD)
    peak_dA = max(abs(f[4]) for f in rows)
    peak_aA = max(abs(f[5]) for f in rows)
    peak_v = max(abs(f[1]) for f in rows)
    pressed = any(f[3] for f in rows)
    details.append((r, statistics.mean(abs_err), max(abs_err), under, sat, peak_dA, peak_aA, peak_v, pressed, len(rows)))

  for d in sorted(details, key=lambda x: -x[2]):
    r, avg_err, max_err, under, sat, peak_dA, peak_aA, peak_v, pressed, n = d
    print(f"{r['seg']:>3} {r['t0']:>6.0f} {r['dur']:>5.1f} {peak_dA:>6.2f} {peak_aA:>6.2f} {avg_err:>7.3f} {max_err:>7.3f} {under:>5} {sat:>5} {peak_v*3.6:>5.0f} {'是' if pressed else '':>3}")

  all_abs_err = []
  under_total = 0
  sat_total = 0
  total = 0
  for d in details:
    r = d[0]
    for f in r['rows']:
      all_abs_err.append(abs(f[6]))
      total += 1
      if f[6] is not None and f[6] > UNDER_THRESHOLD:
        under_total += 1
      if f[7] is not None and abs(f[7]) > SAT_RATIO:
        sat_total += 1

  print(f"\n=== 汇总（{total} 个弯道帧）===")
  if total > 0:
    print(f"平均|误差|: {statistics.mean(all_abs_err):.3f} m/s² | 最大: {max(all_abs_err):.3f}")
    print(f"转向不足帧(>0.3): {under_total} ({under_total/total*100:.1f}%)")
    print(f"扭矩饱和帧: {sat_total} ({sat_total/total*100:.1f}%)")
    sharp = [d for d in details if d[5] > 1.5]
    if sharp:
      print(f"\n=== 急弯专项（dAmax>1.5m/s²，{len(sharp)} 个）===")
      print(f"急弯平均|误差|: {statistics.mean(d[1] for d in sharp):.3f} m/s²")
      sharp_under = sum(1 for d in sharp if d[3] >= 3)
      print(f"含转向不足的急弯: {sharp_under}/{len(sharp)}")

    if statistics.mean(all_abs_err) < 0.25 and under_total / total < 0.05:
      print("\n结论: 转向放大系数 1.0 足够（弯道误差小、无系统性转向不足、扭矩不饱和）")
    elif statistics.mean(all_abs_err) < 0.4 and under_total / total < 0.15:
      print("\n结论: 系数 1.0 基本够用，个别急弯略弱，可试 1.05~1.1")
    else:
      print("\n结论: 存在转向不足/扭矩饱和，建议系数 1.1~1.2 后复测")


if __name__ == '__main__':
  main()
