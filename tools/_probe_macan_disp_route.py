"""实车回放：仪表 ACC_02.ACC_Abstandsindex 的显示源是原厂雷达(idx)还是 OP 融合(dRel)。

证据来源（三条独立信号）：
  - OP 发出的 CAN 事件里 addr=780 / src=0 的 ACC_02 -> OP 实际发给仪表的 Abstandsindex（ground truth）
  - 接收 CAN 事件里 addr=780 / src=2 的 ACC_02      -> 原厂雷达自己的 Abstandsindex（候选源 a）
  - radarState.leadOne.dRel                         -> OP 融合后前车距离（候选源 b）
"""
import sys
sys.path.insert(0, '/data/openpilot')
from openpilot.tools.lib.logreader import LogReader

SENT_EV = 'send' + 'can'

MACAN_B1_T_A = 0.008969
MACAN_B1_T_B = 0.332


def drel_to_idx(drel, vego):
  t = drel / vego if vego > 5.0 else drel / 5.0
  return int(round((t - MACAN_B1_T_B) / MACAN_B1_T_A))


def idx_to_drel(idx, vego):
  t = MACAN_B1_T_A * idx + MACAN_B1_T_B
  return t * (vego if vego > 5.0 else 5.0)


def replay(path):
  stock_idx = 0
  stock_obj = 0
  vego = 0.0
  lead_present = False
  lead_drel = 0.0
  rows = []
  for e in LogReader(path, sort_by_time=True):
    w = e.which()
    if w == 'can':
      for m in e.can:
        if m.src != 2 or m.address != 780:
          continue
        d = bytes(m.dat)
        stock_idx = (d[3] | (d[4] << 8)) & 0x3FF
        stock_obj = (d[5] >> 6) & 0x3
    elif w == 'carState':
      vego = e.carState.vEgo
    elif w == 'radarState':
      lead_present = e.radarState.leadOne.present
      if lead_present:
        lead_drel = e.radarState.leadOne.dRel
    elif w == SENT_EV:
      for m in e.__getattr__(SENT_EV):
        if m.src == 0 and m.address == 780:
          d = bytes(m.dat)
          sent_idx = (d[3] | (d[4] << 8)) & 0x3FF
          fused = drel_to_idx(lead_drel, vego) if (lead_present and lead_drel > 0) else 0
          rows.append(dict(t=e.logMonoTime / 1e9, vego=vego, stock=stock_idx, obj=stock_obj,
                           sent=sent_idx, fused=fused, lp=lead_present, drel=lead_drel))
  return rows


def summarize(path):
  rows = replay(path)
  tag = path.split('/')[-2]
  if not rows:
    print(tag, ': 无 OP 发出的 ACC_02')
    return
  n = len(rows)
  m_stock = sum(1 for r in rows if r['sent'] == r['stock'])
  m_fused = sum(1 for r in rows if r['fused'] > 0 and abs(r['sent'] - r['fused']) <= 1)
  both = sum(1 for r in rows if r['sent'] == r['stock'] and r['fused'] > 0 and abs(r['sent'] - r['fused']) <= 1)
  print()
  print('=== ', tag, ' :', n, '帧 ===')
  print('  发出==原厂idx        :', m_stock, '(', round(100 * m_stock / n, 1), '%)')
  print('  发出==融合idx(+/-1)  :', m_fused, '(', round(100 * m_fused / n, 1), '%)')
  print('  两者相同(不可区分)    :', both, '(', round(100 * both / n, 1), '%)')
  print('  原厂有目标(obj=1)     :', sum(1 for r in rows if r['obj']))
  print('  融合 lead 存在        :', sum(1 for r in rows if r['lp']))
  print('  原厂有目标 但 融合缺失 :', sum(1 for r in rows if r['obj'] and not r['lp']))
  lf = [r for r in rows if r['lp'] and r['drel'] > 0]
  if lf:
    print('  【有融合 lead 的帧】', len(lf), '帧:')
    print('    其中 sent==原厂idx :', sum(1 for r in lf if r['sent'] == r['stock']))
    print('    其中 sent==融合idx :', sum(1 for r in lf if abs(r['sent'] - r['fused']) <= 1))
    print('    其中 都不是(平滑/保持):', sum(1 for r in lf if abs(r['sent'] - r['fused']) > 1 and r['sent'] != r['stock']))
  print('  采样:')
  for i, r in enumerate(rows):
    if i < 10 or i % 60 == 0:
      print('    t=%8.2f v=%5.1f stock=%4d(%5.1fm) fused=%4d leadP=%d -> sent=%4d'
            % (r['t'], r['vego'], r['stock'], idx_to_drel(r['stock'], r['vego']), r['fused'], int(r['lp']), r['sent']))


if __name__ == '__main__':
  for p in sys.argv[1:]:
    summarize(p)
