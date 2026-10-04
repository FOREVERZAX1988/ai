"""route 90：① 校验 bus128(写回 receipt) 的 ACC_02 值 == OP 实际发出值；
② 2.A 前后（旧/新）逐帧重算 vs 日志实发值。"""
import sys, glob, os
sys.path.insert(0, '/data/openpilot')
sys.path.insert(0, '/data/openpilot/ai/tools')
from openpilot.tools.lib.logreader import LogReader
import macan_disp_lib as L

SENT = 'send' + 'can'


def run(path):
  st = dict(stock=0, srel=0, vego=0.0, lp=False, ldrel=0.0, lvlead=0.0)
  tx = []; rcpt = []
  for e in LogReader(path, sort_by_time=True):
    w = e.which()
    if w == 'can':
      for m in e.can:
        b = bytes(m.dat)
        if m.address == 780 and m.src == 2:
          st['stock'] = (b[3] | (b[4] << 8)) & 0x3FF
          st['srel'] = (b[5] >> 6) & 0x3
        elif m.address == 780 and m.src == 128:
          rcpt.append((b[3] | (b[4] << 8)) & 0x3FF)
    elif w == 'carState':
      st['vego'] = e.carState.vEgo
    elif w == 'radarState':
      lo = e.radarState.leadOne
      st['lp'] = lo.present
      st['ldrel'] = lo.dRel if lo.present else 0.0
      st['lvlead'] = lo.vLead if lo.present else 0.0
    elif w == SENT:
      for m in getattr(e, SENT):
        if m.address == 780:
          b = bytes(m.dat)
          tx.append(dict(logged=(b[3] | (b[4] << 8)) & 0x3FF, **st))
  return tx, rcpt


def replay(rows, fused):
  cc, _ = L.build_cc()
  L.reset(cc); cc.macan_disp_fused = fused
  return [L.step(cc, r['vego'], r['stock'], r['srel'], r['ldrel'], r['lvlead'], 0.0, i)[:2]
          for i, r in enumerate(rows)]


TOT = dict(n=0, stk=0, pres=0, logp=0, oldp=0, newp=0, diff=0, mo=0, mn=0, rn=0, req=0)
for d in sorted(glob.glob(sys.argv[1])):
  p = os.path.join(d, 'rlog.zst')
  if not os.path.exists(p):
    continue
  tx, rcpt = run(p)
  old = replay(tx, False); new = replay(tx, True)
  n = len(tx)
  c = dict(n=n, stk=sum(1 for r in tx if r['stock'] > 0), pres=sum(1 for r in tx if r['lp']),
           logp=sum(1 for r in tx if r['logged'] > 0), oldp=sum(1 for o in old if o[0] > 0),
           newp=sum(1 for x in new if x[0] > 0),
           diff=sum(1 for o, x in zip(old, new) if o[0] != x[0]),
           mo=sum(1 for o, r in zip(old, tx) if o[0] == r['logged']),
           mn=sum(1 for x, r in zip(new, tx) if x[0] == r['logged']),
           rn=len(rcpt), req=sum(1 for a, r in zip(rcpt, tx) if a == r['logged']))
  print('SEG %s  frames=%-5d 原厂idx>0=%-3d leadOne=%-4d 日志idx>0=%-4d 旧>0=%-4d 新>0=%-4d 旧!=新=%-3d '
        '日志==旧=%-5d 日志==新=%-5d bus128帧=%-5d bus128与实发相同=%d'
        % (os.path.basename(d), c['n'], c['stk'], c['pres'], c['logp'], c['oldp'], c['newp'],
           c['diff'], c['mo'], c['mn'], c['rn'], c['req']))
  for k, v in c.items():
    if k != 'n':
      TOT[k] += v
  TOT['n'] += n
print()
print('合计 frames=%(n)d | 原厂idx>0=%(stk)d | leadOne.present=%(pres)d | 日志发出idx>0=%(logp)d | '
      '旧逻辑>0=%(oldp)d | 2.A新逻辑>0=%(newp)d | 旧!=新=%(diff)d | 日志==旧=%(mo)d | 日志==新=%(mn)d | '
      'bus128帧=%(rn)d 相同=%(req)d' % TOT)
