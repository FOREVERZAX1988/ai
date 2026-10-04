"""原厂 ACC_02(src=2, bus2) 字段经验语义：Display_Prio(44|2) vs Abstandsindex(24|10) / Relevantes_Objekt(46|2)
/ Status_Anzeige(61|3)，以及 OP 代发 ACC_02(src=0) 的同字段取值。"""
import sys, glob, os, collections
sys.path.insert(0, '/data/openpilot')
from openpilot.tools.lib.logreader import LogReader
SENT = 'send' + 'can'


def dec(d):
  return dict(ab=(d[3] | (d[4] << 8)) & 0x3FF,
              rel=(d[5] >> 6) & 0x3,
              prio=(d[5] >> 4) & 0x3,
              txt=(d[6] & 0x7F),
              anz=(d[7] >> 5) & 0x7)


for pat in sys.argv[1:]:
  for d in sorted(glob.glob(pat)):
    p = os.path.join(d, 'rlog.zst')
    if not os.path.exists(p):
      continue
    hs = collections.Counter(); ho = collections.Counter(); n = 0
    for e in LogReader(p, sort_by_time=True):
      w = e.which()
      if w == 'can':
        for m in e.can:
          if m.address == 780 and m.src == 2:
            f = dec(bytes(m.dat)); hs[(f['ab'] > 0, f['rel'], f['prio'], f['anz'])] += 1
      elif w == SENT:
        for m in getattr(e, SENT):
          if m.address == 780:
            f = dec(bytes(m.dat)); ho[(f['ab'] > 0, f['rel'], f['prio'], f['anz'])] += 1
            n += 1
    print('SEG %s  OP-tx=%d' % (os.path.basename(d), n))
    print('  原厂(src2): (ab>0,relev,prio,status_anz) -> 帧数')
    for k, v in sorted(hs.items(), key=lambda x: -x[1])[:8]:
      print('    %s -> %d' % (k, v))
    print('  OP发出(src0): (ab>0,relev,prio,status_anz) -> 帧数')
    for k, v in sorted(ho.items(), key=lambda x: -x[1])[:8]:
      print('    %s -> %d' % (k, v))
