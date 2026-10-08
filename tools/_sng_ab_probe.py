#!/usr/bin/env python3
"""_sng_ab_probe.py —— SnG / idx 融合专项探针（方案A vs 方案B 取证）

用法:
  _sng_ab_probe.py seginfo <route>            # 每个 seg 的 t 范围 / 静止帧 / idx 统计（定位段）
  _sng_ab_probe.py hold <route> [vth]         # idx 常量保持段（静止 vs 行进）统计
  _sng_ab_probe.py timeline <route> <seg> <lo> <hi>   # 逐变化时间线（相对 seg 首帧秒）
  _sng_ab_probe.py pairs <route...>           # 视觉 dRel  vs  原厂 idx 关系（低速/静止标定）

route 传入形如 '00000091--98208e01cb'，脚本自己 glob 所有 seg。
"""
import glob
import os
import sys

sys.path.insert(0, '/data/openpilot')

from openpilot.tools.lib.logreader import LogReader


def g(x, s, n):
  return (int.from_bytes(x, 'little') >> s) & ((1 << n) - 1)


def segs(route):
  return sorted(glob.glob('/data/media/0/realdata/%s--*/rlog.zst' % route),
                key=lambda p: int(os.path.basename(os.path.dirname(p)).split('--')[-1]))


def scan(path, want=None):
  """单遍扫描，yield 每帧 (t, kind, payload)。want=None 表示全要。"""
  for e in LogReader(path):
    w = e.which()
    if w == 'can':
      for m in e.can:
        x = bytes(m.dat)
        if m.address == 780:
          yield (e.logMonoTime / 1e9, 'ACC02', (m.src,
                                               (x[3] | (x[4] << 8)) & 0x3FF,
                                               (x[5] >> 6) & 3,
                                               g(x, 44, 2),
                                               g(x, 22, 2),
                                               g(x, 12, 10)))
        elif m.address == 269:
          yield (e.logMonoTime / 1e9, 'ACC05', (m.src, g(x, 57, 3), g(x, 16, 10),
                                                g(x, 62, 1), g(x, 43, 1)))
    elif w == 'carState':
      cs = e.carState
      yield (e.logMonoTime / 1e9, 'CS', (round(cs.vEgo, 2), int(cs.standstill),
                                         int(cs.gasPressed), int(cs.brakePressed),
                                         int(cs.cruiseState.enabled),
                                         round(cs.cruiseState.speed * 3.6, 1),
                                         int(cs.accFaulted)))
    elif w == 'radarState':
      ld = e.radarState.leadOne
      yield (e.logMonoTime / 1e9, 'RD', (int(ld.present), int(ld.radar),
                                         round(ld.dRel, 1), round(ld.vRel, 2),
                                         round(ld.vLead, 2), round(ld.modelProb, 2)))
    elif w == 'controlsState':
      yield (e.logMonoTime / 1e9, 'CT', (int(e.controlsState.enabled),
                                         int(e.controlsState.longControlState),
                                         round(e.controlsState.forceDecel or 0.0, 1)))
    elif w == 'carControl':
      yield (e.logMonoTime / 1e9, 'CC', (round(e.carControl.actuators.accel, 2),
                                         int(e.carControl.longActive),
                                         int(e.carControl.enabled)))
    elif w == 'selfdriveState':
      yield (e.logMonoTime / 1e9, 'SS', (int(e.selfdriveState.enabled),
                                         str(e.selfdriveState.state)))


def report_name(path):
  return os.path.basename(os.path.dirname(path))


def cmd_seginfo(route):
  for p in segs(route):
    first = last = None
    n_cs = 0
    stand = 0
    idx2 = {}
    st2 = {}
    fault = 0
    for t, k, v in scan(p):
      if first is None:
        first = t
      last = t
      if k == 'CS':
        n_cs += 1
        stand += v[1]
        fault += v[6]
      elif k == 'ACC02' and v[0] == 2:
        idx2[v[1]] = idx2.get(v[1], 0) + 1
      elif k == 'ACC05' and v[0] == 2:
        st2[v[1]] = st2.get(v[1], 0) + 1
    top = sorted(idx2.items(), key=lambda kv: -kv[1])[:4]
    print(f"{report_name(p)} t {first - first0:.1f}~{last - first0:.1f}  CSf={n_cs} stand={stand} "
          f"accFaulted={fault} idx2top={top} st2={sorted(st2.items(), key=lambda kv: -kv[1])[:4]}")


def cmd_hold(route, vth=0.15):
  """报告 idx（bus2）长时间恒定的区间：分静止(v<vth) / 行进。"""
  for p in segs(route):
    rows = []
    for t, k, v in scan(p):
      if k == 'ACC02' and v[0] == 2:
        rows.append((t, v[1]))
      elif k == 'CS':
        rows.append((t, None, v[0]))
    if not rows:
      continue
    runs = []
    cur_i = cur_n = None
    start = None
    for r in rows:
      if len(r) == 2:
        t, i = r
        if i != cur_i:
          if cur_i is not None and cur_n >= 20:
            runs.append((start, t, cur_i, cur_n))
          cur_i, cur_n, start = i, 1, t
        else:
          cur_n += 1
    out = [r for r in runs if r[2] > 0]
    if out:
      print(f"--- {report_name(p)} 常量 idx 段（>=2s）: n={len(out)} "
            f"最长={max(r[1] - r[0] for r in out):.1f}s")
      for r in sorted(out, key=lambda r: -(r[1] - r[0]))[:8]:
        print(f"    t {r[0] - first0:7.1f}~{r[1] - first0:7.1f} ({r[1] - r[0]:5.1f}s) idx={r[2]}")


def cmd_timeline(route, segidx, lo, hi):
  p = segs(route)[int(segidx)]
  prev = {}
  rows = []
  for t, k, v in scan(p):
    rows.append((t, k, v))
  if not rows:
    print('empty')
    return
  t0 = rows[0][0]
  idx2 = idxop = None
  for t, k, v in rows:
    rt = t - t0
    if rt < lo or rt > hi:
      continue
    if k == 'RD':
      key, val = 'RD', (v[0], v[2], v[3], v[4])
    elif k == 'ACC02':
      key = 'F2' if v[0] == 2 else 'O2'
      val = (v[1], v[2], v[3], v[4])
    elif k == 'ACC05':
      key = 'F5' if v[0] == 2 else 'O5'
      val = (v[1], v[2], v[3], v[4])
    elif k == 'CS':
      key, val = 'CS', (v[0], v[1], v[2], v[3], v[4], v[5], v[6])
    else:
      key, val = k, v
    if prev.get(key) == val:
      continue
    prev[key] = val
    print(f"{rt:7.2f} {key:3s} {val}")
  print('frames in window:', sum(1 for t, k, v in rows if lo <= t - t0 <= hi))


def cmd_pairs(routes):
  """收集 视觉 dRel / 原厂 idx / v 三元组，输出低速标定统计。"""
  data = []
  for route in routes:
    for p in segs(route):
      idx = 0
      lead = (0, 0.0, 0.0)
      v = 0.0
      for t, k, val in scan(p):
        if k == 'ACC02' and val[0] == 2:
          idx = val[1]
        elif k == 'CS':
          v = val[0]
        elif k == 'RD':
          lead = (val[0], val[2], val[3])
          if lead[0] and idx > 0 and lead[1] > 0.5:
            data.append((idx, v, lead[1], lead[2], route, p))
  print('样本', len(data))
  if not data:
    return
  import statistics as st
  for lo, hi, name in [(0.0, 0.3, '静止 v<0.3'), (0.3, 1.0, '极低速 .3-1'),
                       (1.0, 2.0, '低速 1-2'), (2.0, 5.0, '低速 2-5'), (5.0, 100., '常规 >5')]:
    sub = [d for d in data if lo <= d[1] < hi]
    if len(sub) < 5:
      print(f"{name}: n={len(sub)} 样本不足")
      continue
    ks = [d[0] / d[2] for d in sub]          # idx/d  -> 越大表示 idx 相对距离"偏大"
    d30 = [d[2] - d[0] / 30.0 for d in sub]  # 假设 d = idx/30 的残差
    print(f"{name}: n={len(sub)} idx中位={st.median([d[0] for d in sub]):.0f} "
          f"视觉d中位={st.median([d[2] for d in sub]):.1f}m "
          f"idx/d中位={st.median(ks):.2f} (idx=d*k)  "
          f"d-idx/30 残差中位={st.median(d30):+.2f}m "
          f"idx/(v*d)中位={st.median([d[0] / max(d[1] * d[2], 1e-3) for d in sub]):.1f}")
  # 静止样本详表（前 25 条）
  low = [d for d in data if d[1] < 1.0][:25]
  print('\n低速样本样例 (route idx v dRel vRel):')
  for d in low:
    print(f"  {d[4][-2:]} idx={d[0]:4d} v={d[1]:4.1f} visd={d[2]:5.1f} vRel={d[3]:+.2f} "
          f"idx/30={d[0] / 30.0:5.2f}")


if __name__ == '__main__':
  mode = sys.argv[1]
  first0 = None
  # 记录 route 首帧时间（用于相对打印）
  if mode in ('seginfo', 'hold'):
    ps = segs(sys.argv[2])
    for t, k, v in scan(ps[0]):
      first0 = t
      break
  if mode == 'seginfo':
    cmd_seginfo(sys.argv[2])
  elif mode == 'hold':
    cmd_hold(sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 0.15)
  elif mode == 'timeline':
    cmd_timeline(sys.argv[2], sys.argv[3], float(sys.argv[4]), float(sys.argv[5]))
  elif mode == 'pairs':
    cmd_pairs(sys.argv[2:])
  else:
    print(__doc__)
