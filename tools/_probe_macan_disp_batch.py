"""批量回放所有本地 route 段，汇总"仪表车距显示源"统计。"""
import sys, glob, os
sys.path.insert(0, '/data/openpilot')
sys.path.insert(0, '/data/openpilot/ai/tools')
import macan_disp_lib as L
from _probe_macan_disp_replay import frames, d2i

ROOT = '/data/media/0/realdata'

def one(path):
  rows = frames(path)
  if not rows:
    return None
  cc, _ = L.build_cc()
  L.reset(cc)
  hit = 0
  for i, r in enumerate(rows):
    ab, rele, latch = L.step(cc, r['vego'], r['stock'], r['obj'], r['drel'], 15.0, 0.0, i)
    r['pred'] = ab
    r['latch'] = latch
    if ab == r['logged']:
      hit += 1
  n = len(rows)
  tgt = [r for r in rows if (0 < r['stock'] < 1021) or r['drel'] > 0]
  rad = [r for r in tgt if 0 < r['stock'] < 1021]
  fus = [r for r in tgt if r['drel'] > 0]
  return dict(seg=os.path.basename(os.path.dirname(path)) + ':' + os.path.basename(path).split('-')[-1][0],
              n=n, hit=hit, tgt=len(tgt), rad=len(rad), fus=len(fus),
              s_stock=sum(1 for r in tgt if r['logged'] == r['stock']),
              s_fused=sum(1 for r in tgt if r['drel'] > 0 and abs(r['logged'] - d2i(r['drel'], r['vego'])) <= 1),
              latch=sum(1 for r in tgt if r['latch']),
              vmax=max(r['vego'] for r in rows) * 3.6)

paths = []
for d in sorted(glob.glob(os.path.join(ROOT, '*'))):
  for f in sorted(glob.glob(os.path.join(d, 'rlog.zst'))):
    paths.append(f)
print('routes found:', len(paths))
print('%-26s %6s %6s %6s %6s %6s %6s %6s %6s %7s' % ('seg', 'frames', 'match%', '有目标', '原厂有', '融合有', '→原厂', 'latch', '→融合', 'vmax'))
tot = dict(n=0, hit=0, tgt=0, rad=0, s_stock=0, s_fused=0, latch=0, fus=0)
for p in paths:
  r = one(p)
  if r is None:
    print('%-26s  (无帧)' % p.split('/')[-2]); continue
  print('%-26s %6d %5.1f%% %6d %6d %6d %6d %6d %6d %6.0f' % (
      r['seg'], r['n'], 100 * r['hit'] / r['n'], r['tgt'], r['rad'], r['fus'], r['s_stock'], r['latch'], r['s_fused'], r['vmax']))
  for k in ('n', 'hit', 'tgt', 'rad', 's_stock', 's_fused', 'latch', 'fus'):
    tot[k] += r[k]
print()
print('合计: frames=%d match=%.1f%% 有目标=%d / 原厂有目标=%d(→原厂idx %d, latch %d) / 融合有目标=%d(→融合idx %d)'
      % (tot['n'], 100 * tot['hit'] / tot['n'], tot['tgt'], tot['rad'], tot['s_stock'], tot['latch'], tot['fus'], tot['s_fused']))
