"""src2 ACC_02 逐帧时间线 + 同步 ACC_05.st / TSK_04 状态（定位 Display_Prio 语义）。"""
import sys, glob
sys.path.insert(0, '/data/openpilot')
from openpilot.tools.lib.logreader import LogReader

p = sorted(glob.glob(sys.argv[1]))[0] if '*' in sys.argv[1] else sys.argv[1]
only_win = len(sys.argv) > 2


def dec(d):
  return dict(ab=(d[3] | (d[4] << 8)) & 0x3FF, rel=(d[5] >> 6) & 0x3,
              prio=(d[5] >> 4) & 0x3, txt=d[6] & 0x7F, anz=(d[7] >> 5) & 0x7,
              wun=((d[1] | (d[2] << 8)) >> 4) & 0x3FF)


rows = []
cur = {'st': -1, 'tsk': -1}
for e in LogReader(p, sort_by_time=True):
  if e.which() != 'can':
    continue
  for m in e.can:
    d = bytes(m.dat)
    if m.address == 269:
      cur['st'] = (d[7] >> 1) & 0x7
    elif m.address == 270:
      cur['tsk'] = (d[7] >> 6) & 0x3
    elif m.address == 780 and m.src == 2:
      f = dec(d); f['t'] = e.logMonoTime / 1e9; f['st'] = cur['st']; f['tsk'] = cur['tsk']
      rows.append(f)

print('frames=%d ab>0=%d' % (len(rows), sum(1 for r in rows if r['ab'] > 0)))
if rows:
  t0 = rows[0]['t']
  if only_win:
    for r in rows:
      if r['ab'] > 0:
        t0 = r['t'] - 1.5; break
  print('%-7s %6s %4s %5s %4s %6s %4s %4s %4s' % ('t', 'ab', 'rel', 'prio', 'anz', 'wunsch', 'st', 'tsk', 'txt'))
  last = None
  for r in rows:
    if only_win and r['t'] < t0:
      continue
    key = (r['ab'], r['rel'], r['prio'], r['anz'], r['st'], r['tsk'])
    if only_win or key != last:
      print('%-7.2f %6d %4d %5d %4d %6.1f %4d %4d %4d'
            % (r['t'] - t0, r['ab'], r['rel'], r['prio'], r['anz'], r['wun'] * 0.32,
               r['st'], r['tsk'], r['txt']))
      last = key
