"""判别 ACC_02.Display_Prio 语义（2026-10-04，用户假设复核）。

用户假设 H_bars：Display_Prio 才是仪表"2/3/4 格车距"的真实信号。
对抗假设 H_gate：Display_Prio 只是显示优先级/模式位（透传原厂，不携带距离信息），
                 真值由 Abstandsindex(24|10)+Relevantes_Objekt(46|2) 决定。

判别量（全部取 src=2 原厂帧）：
  A) prio vs ACC_Gesetzte_Zeitluecke(37|3, 司机 DIST 键设定的格数)  → H_bars 要求强 1:1
  B) prio vs ACC_Anzeige_Zeitluecke(42|1)                          → 格数"正在被显示"标志
  C) prio vs sign(d ab)（收窄/拉开），限 rel>0 & ab>0              → H_gate 的已知相关
  D) prio vs ACC_Status_Anzeige(61|3) / Prim_Anz(22|2) 独立性
用法: python3 ai/tools/_probe_prio_vs_zeitluecke.py '/data/media/0/realdata/0000009*--*/rlog.zst'
"""
import sys, glob, os, collections
sys.path.insert(0, '/data/openpilot')
from openpilot.tools.lib.logreader import LogReader


def bits(d, start, length):
  v = 0
  for i in range(length):
    b = start + i
    v |= ((d[b >> 3] >> (b & 7)) & 1) << i
  return v


def dec(d):
  return dict(ab=bits(d, 24, 10), rel=bits(d, 46, 2), prio=bits(d, 44, 2),
              zl=bits(d, 37, 3), zlan=bits(d, 42, 1), anz=bits(d, 22, 2),
              st=bits(d, 61, 3), txt=bits(d, 48, 7))


paths = []
for pat in sys.argv[1:]:
  paths += sorted(glob.glob(pat))
paths = [p for p in paths if os.path.exists(p)]

A = collections.Counter()   # (zl, prio)
B = collections.Counter()   # (zlan, prio)
C = collections.Counter()   # (rel>0, d_ab sign, prio)
D = collections.Counter()   # (st, prio)
P = collections.Counter()   # prio 全局
Z = collections.Counter()   # zl 全局
nseg = 0

for p in paths:
  nseg += 1
  prev_ab = None
  for e in LogReader(p, sort_by_time=True):
    if e.which() != 'can':
      continue
    for m in e.can:
      if m.address != 780 or m.src != 2 or len(m.dat) < 8:
        continue
      f = dec(bytes(m.dat))
      P[f['prio']] += 1
      Z[f['zl']] += 1
      A[(f['zl'], f['prio'])] += 1
      B[(f['zlan'], f['prio'])] += 1
      D[(f['st'], f['prio'])] += 1
      if prev_ab is not None:
        d_ab = f['ab'] - prev_ab
        sgn = 'shrink(<=0)' if d_ab <= 0 else 'open(>0)'
        C[(f['rel'] > 0 and f['ab'] > 0, sgn, f['prio'])] += 1
      prev_ab = f['ab']

print('segments=%d' % nseg)
print('\n== prio 全局分布 ==', dict(sorted(P.items())))
print('== Gesetzte_Zeitluecke(格数) 全局分布 ==', dict(sorted(Z.items())))
print('\n== A) (Gesetzte_Zeitluecke, prio) ==')
for k, v in sorted(A.items()):
  print('   zl=%d prio=%d -> %d' % (k[0], k[1], v))
print('\n== B) (Anzeige_Zeitluecke, prio) ==')
for k, v in sorted(B.items()):
  print('   zlan=%d prio=%d -> %d' % (k[0], k[1], v))
print('\n== C) (目标有效, d(ab)方向, prio) ==')
for k, v in sorted(C.items()):
  print('   valid=%s %s prio=%d -> %d' % (k[0], k[1], k[2], v))
print('\n== D) (Status_Anzeige, prio) ==')
for k, v in sorted(D.items()):
  print('   st=%d prio=%d -> %d' % (k[0], k[1], v))
