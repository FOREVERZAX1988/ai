"""2.A 前后对比：真实 route 回放，「旧显示源」vs「新显示源（=控制源，仅 Macan）」。

旧 = Macan 改动前逻辑（本工具用 `cc.macan_disp_fused=False` 复现：原厂 idx 透传 + 视觉补位
     + 30%/20% 迟滞 + 2s hold），先验证它能复现日志实际发出的值（证明回放口径可靠）；
新 = 2.A（只跟 radard 融合 leadOne 反算，无 hold）。

输出：逐段 + 合计的差异分类
  - 旧有车→新无车（控制侧无 lead）：真正的「仪表有车/控制无车」被清零
  - 两源都有目标但数值不同：显示口径由原厂 idx 改为控制（融合）距离
  - 旧无车→新有车：预期为空（若出现说明 hold/迟滞丢弃了控制侧真实 lead）
用法：python3 ai/tools/_probe_macan_disp_2a_diff.py [最多路段数]
"""
import sys, glob, os
sys.path.insert(0, '/data/openpilot')
sys.path.insert(0, '/data/openpilot/ai/tools')
import macan_disp_lib as L
from _probe_macan_disp_replay import frames

ROOT = '/data/media/0/realdata'
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 10**9


def replay(rows, fused):
  cc, _ = L.build_cc()
  L.reset(cc)
  cc.macan_disp_fused = fused
  out = []
  for i, r in enumerate(rows):
    vlead = 15.0 if r['drel'] > 0 else 0.0
    ab, rele, _latch = L.step(cc, r['vego'], r['stock'], r['obj'], r['drel'], vlead, 0.0, i)
    out.append((ab, rele))
  return out


paths = []
for d in sorted(glob.glob(os.path.join(ROOT, '*'))):
  paths.extend(sorted(glob.glob(os.path.join(d, 'rlog.zst'))))
paths = paths[:LIMIT]

tot = dict(n=0, match_old=0, same=0, lost=0, both=0, gained=0, dsum=0.0)
print('%-28s %6s %9s %7s %9s %7s %7s %9s' % ('seg', 'frames', 'old复现%', '相同', '旧→无车', '两边有', '无→有车', '|Δ|均值'))
for p in paths:
  rows = frames(p)
  if not rows:
    continue
  old = replay(rows, False)
  new = replay(rows, True)
  n = len(rows)
  match_old = sum(1 for (ab, _), r in zip(old, rows) if ab == r['logged'])
  same = lost = both = gained = 0
  dsum = 0.0
  for (o, _ro), (nv, _rn) in zip(old, new):
    if o == nv:
      same += 1
    elif o > 0 and nv == 0:
      lost += 1
    elif o > 0 and nv > 0:
      both += 1
      dsum += abs(o - nv)
    else:
      gained += 1
  seg = os.path.basename(os.path.dirname(p)) + ':' + os.path.basename(p).split('-')[-1][0]
  print('%-28s %6d %8.1f%% %7d %9d %7d %7d %9.1f'
        % (seg, n, 100 * match_old / n, same, lost, both, gained, dsum / both if both else 0.0))
  tot['n'] += n; tot['match_old'] += match_old; tot['same'] += same
  tot['lost'] += lost; tot['both'] += both; tot['gained'] += gained; tot['dsum'] += dsum

print()
print('合计 frames=%d  旧逻辑复现日志=%.2f%%  相同=%d(%.1f%%)  旧→无车=%d  两边有=%d(|Δ|均值 %.1f idx)  无→有车=%d'
      % (tot['n'], 100 * tot['match_old'] / max(tot['n'], 1), tot['same'], 100 * tot['same'] / max(tot['n'], 1),
         tot['lost'], tot['both'], tot['dsum'] / tot['both'] if tot['both'] else 0.0, tot['gained']))
