"""Display_Prio vs ACC_05 减速请求(ACC_Verz_anf 32|11 / ACC_Momentenanforderung 16|10) 与 st。"""
import sys, glob, os, collections
sys.path.insert(0, '/data/openpilot')
from openpilot.tools.lib.logreader import LogReader

tab = collections.Counter()
for pat in sys.argv[1:]:
  for d in sorted(glob.glob(pat)):
    p = os.path.join(d, 'rlog.zst')
    if not os.path.exists(p):
      continue
    st = -1; verz = 0.0; mom = 0
    for e in LogReader(p, sort_by_time=True):
      if e.which() != 'can':
        continue
      for m in e.can:
        b = bytes(m.dat)
        if m.address == 269:
          st = (b[7] >> 1) & 0x7
          verz = (((b[4] | (b[5] << 8)) >> 0) & 0x7FF) * 0.005 - 7.22
          mom = (b[2] | (b[3] << 8)) & 0x3FF
        elif m.address == 780 and m.src == 2:
          ab = (b[3] | (b[4] << 8)) & 0x3FF
          rel = (b[5] >> 6) & 0x3
          prio = (b[5] >> 4) & 0x3
          vz = 'neg' if verz < -0.15 else ('pos' if verz > 0.05 else 'zero')
          mn = '0' if mom == 0 else ('hi>500' if mom > 500 else 'lo<=500')
          tab[(ab > 0, rel, prio, st, vz, mn)] += 1
for k, v in sorted(tab.items(), key=lambda x: -x[1])[:22]:
  print('  (ab>0,rel,prio,st,verz,mom)=%s -> %d' % (k, v))
