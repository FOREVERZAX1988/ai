"""日志回放校验：用真实 CarController 逐帧重算仪表 ACC_02，与日志里实际发出的值比对。

若重算值与日志实际发出值高度一致 -> 证明"显示源判定模型"就是现场行为。
"""
import sys
sys.path.insert(0, '/data/openpilot')
sys.path.insert(0, '/data/openpilot/ai/tools')
from openpilot.tools.lib.logreader import LogReader
import macan_disp_lib as L

SENT_EV = 'send' + 'can'
A = 0.008969
B = 0.332


def d2i(drel, v):
  t = drel / v if v > 5.0 else drel / 5.0
  return int(round((t - B) / A))


def frames(path):
  stock, obj, vego, lp, drel = 0, 0, 0.0, False, 0.0
  out = []
  for e in LogReader(path, sort_by_time=True):
    w = e.which()
    if w == 'can':
      for m in e.can:
        if m.src == 2 and m.address == 780:
          d = bytes(m.dat)
          stock = (d[3] | (d[4] << 8)) & 0x3FF
          obj = (d[5] >> 6) & 0x3
    elif w == 'carState':
      vego = e.carState.vEgo
    elif w == 'radarState':
      lp = e.radarState.leadOne.present
      if lp:
        drel = e.radarState.leadOne.dRel
    elif w == SENT_EV:
      for m in e.__getattr__(SENT_EV):
        if m.src == 0 and m.address == 780:
          d = bytes(m.dat)
          out.append(dict(logged=((d[3] | (d[4] << 8)) & 0x3FF), stock=stock, obj=obj, vego=vego,
                          lp=lp, drel=drel if lp else 0.0))
  return out


def run(path):
  rows = frames(path)
  if not rows:
    print(path, 'no frames'); return
  cc, _ = L.build_cc()
  L.reset(cc)
  hit = 0
  latched_from = None
  latch_hist = []
  for i, r in enumerate(rows):
    ab, rele, latch = L.step(cc, r['vego'], r['stock'], r['obj'], r['drel'], 15.0, 0.0, i)
    r['pred'] = ab
    r['latch'] = latch
    latch_hist.append(latch)
    if latched_from is None and latch:
      latched_from = i
    if ab == r['logged']:
      hit += 1
  n = len(rows)
  print()
  print('===', path.split('/')[-2], n, 'frames ===')
  print('  重算 == 日志实际 :', hit, '/', n, '(', round(100 * hit / n, 1), '%)')
  print('  latch 首次置位帧 :', latched_from)
  print('  latch 为真的帧数 :', sum(latch_hist), '/', n)
  r0 = rows[latched_from - 2] if latched_from and latched_from >= 2 else rows[0]
  if latched_from:
    print('  置位前 (帧%d): stock=%d obj=%d leadP=%d drel=%.1f -> 发出 %d'
          % (latched_from - 1, r0['stock'], r0['obj'], int(r0['lp']), r0['drel'], r0['logged']))
    rr = rows[latched_from]
    print('  置位帧 (帧%d): stock=%d obj=%d leadP=%d drel=%.1f -> 发出 %d'
          % (latched_from, rr['stock'], rr['obj'], int(rr['lp']), rr['drel'], rr['logged']))
  tgt = [r for r in rows if (0 < r['stock'] < 1021) or r['drel'] > 0]
  if tgt:
    print('  【有目标帧】', len(tgt), '其中:')
    print('    sent == 原厂idx   :', sum(1 for r in tgt if r['logged'] == r['stock']))
    print('    sent == 融合idx   :', sum(1 for r in tgt if r['drel'] > 0 and abs(r['logged'] - d2i(r['drel'], r['vego'])) <= 1))
    print('    均不是(平滑/保持)  :', sum(1 for r in tgt if r['logged'] != r['stock'] and not (r['drel'] > 0 and abs(r['logged'] - d2i(r['drel'], r['vego'])) <= 1)))
    rad = [r for r in tgt if 0 < r['stock'] < 1021]
    print('  【原厂雷达有目标帧】', len(rad), '其中 sent==原厂idx:', sum(1 for r in rad if r['logged'] == r['stock']), 'latch:', sum(1 for r in rad if r['latch']))
  print('  采样:')
  step = max(1, n // 25)
  for i in range(0, n, step):
    r = rows[i]
    print('    帧%4d v=%5.1f stock=%4d(%5.1fm) obj=%d leadP=%d fused=%4d latch=%d 日志=%4d 重算=%4d %s'
          % (i, r['vego'], r['stock'], d2i(r['stock'], r['vego']) if r['stock'] else 0, r['obj'],
             int(r['lp']), d2i(r['drel'], r['vego']) if r['drel'] > 0 else 0, r['latch'],
             r['logged'], r['pred'], 'OK' if r['logged'] == r['pred'] else 'X'))


if __name__ == '__main__':
  for p in sys.argv[1:]:
    run(p)
