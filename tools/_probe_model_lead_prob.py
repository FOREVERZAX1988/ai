"""解释“为什么某段没在仪表显示前车”：视觉 lead 头(modelV2.leadsV3) prob 分布 + radarState 门槛。

用法：python3 ai/tools/_probe_model_lead_prob.py '/data/media/0/realdata/0000XXXX--hash--*'
背景：radard.get_lead 要求 lead_prob(非对称滤波后) > 0.5 才发布 leadOne；
      仪表(2.A)= CS.op_lead_dRel = radarState.leadOne.dRel，且 _macan_fuse_leads 只能
      “修正已存在的视觉 lead”，不能凭原厂 idx 凭空造 lead。
"""
import sys, glob, collections
sys.path.insert(0, '/data/openpilot')
from openpilot.tools.lib.logreader import LogReader

pat = sys.argv[1] if len(sys.argv) > 1 else '/data/media/0/realdata/*/rlog.zst'
paths = sorted(glob.glob(pat)) if '*' in pat else [pat]
for p in paths:
  hist = collections.Counter(); n = 0; top = []
  pres = 0; nrs = 0
  for e in LogReader(p, sort_by_time=True):
    w = e.which()
    if w == 'modelV2':
      n += 1
      lv = e.modelV2.leadsV3
      if not len(lv):
        hist['empty'] += 1; continue
      pmax = max(l.prob for l in lv)
      hist['%.1f' % (round(pmax * 10) / 10)] += 1
      if pmax > 0.3 and len(top) < 6:
        i = max(range(len(lv)), key=lambda k: lv[k].prob)
        top.append((round(pmax, 2), round(lv[i].x[0], 1), round(lv[i].y[0], 2)))
    elif w == 'radarState':
      nrs += 1
      pres += 1 if e.radarState.leadOne.present else 0
  print('%s\n  modelV2 帧=%d  maxprob 直方图=%s  >0.3样例=%s\n  radarState 帧=%d  leadOne.present=%d'
        % (p, n, dict(sorted(hist.items())), top, nrs, pres))
