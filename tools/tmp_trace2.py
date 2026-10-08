#!/usr/bin/env python3
"""SnG 取证 v2：idx(bus2/bus128 计数+取值) / 前车目标速度(ACC_04) / 原厂 loes+anh / 按键 / planner。
用法: python3 tmp_trace2.py ROUTE_PREFIX
输出: ai/tools/_t2_<prefix>.txt (逐帧) + _t2_<prefix>_cnt.txt (每段计数)
"""
import sys, os
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader
BASE = '/data/media/0/realdata'
pre = sys.argv[1]
segs = sorted(d for d in os.listdir(BASE) if d.startswith(pre) and os.path.isfile(f'{BASE}/{d}/rlog.zst'))
out = open(f'/data/openpilot/ai/tools/_t2_{pre}.txt', 'w')
cnt = open(f'/data/openpilot/ai/tools/_t2_{pre}_cnt.txt', 'w')
print("seg\tT\tidx2\tidx128\tvis\tdRel\tvRel\tvLead\taTgt\tvEgo\tstd\tst05\ten\tres2\tres128\tres2n\tidx2n\tidx128n\ttgtSpd\tprim\tobj\tzl\tloes\tanh", file=out)
print("seg\tidx2_frames\tidx128_frames\ttgtSpd_frames\tn2\tn128", file=cnt)
for seg in segs:
    st = dict(idx2=0, idx128=0, vis=0.0, dRel=0.0, vRel=0.0, vLead=0.0, aTgt=0.0, vEgo=0.0, std=0,
              st05=-1, en=0, res2=0, res128=0, tgt=0.0, prim=-1, obj=-1, zl=-1, loes=-1, anh=-1)
    n2 = n128 = ntgt = 0
    tt = 0.0
    try:
        for m in LogReader(f'{BASE}/{seg}/rlog.zst'):
            w = m.which()
            if w == 'can':
                for c in m.can:
                    d = c.dat
                    if c.address == 780 and len(d) >= 7:
                        v = (d[3] | (d[4] << 8)) & 0x3FF
                        if c.src == 2:
                            st['idx2'] = v; n2 += 1
                        elif c.src == 128:
                            st['idx128'] = v; n128 += 1
                        st['prim'] = (d[5] >> 6) & 0x3
                        st['obj'] = (d[3] >> 6) & 0x3 if False else ((d[4] >> 4) & 0x3)
                        st['zl'] = (d[4] >> 5) & 7
                    elif c.address == 804 and c.src == 2 and len(d) >= 8:
                        vv = ((d[5] | (d[6] << 8)) & 0x3FF) * 0.32
                        st['tgt'] = vv if vv < 326 else 0.0; ntgt += 1
                    elif c.address == 0x10b and len(d) >= 4:
                        b = int.from_bytes(d[:4], 'little')
                        if c.src == 2:
                            st['res2'] = (b >> 19) & 1
                        elif c.src == 128:
                            st['res128'] = (b >> 19) & 1
                    elif c.address == 0x10d and c.src == 2 and len(d) >= 8:
                        b = int.from_bytes(d[:8], 'little')
                        st['st05'] = (b >> 57) & 7
                        st['loes'] = (b >> 43) & 1
                        st['anh'] = (b >> 62) & 1
            elif w == 'modelV2':
                ld = m.modelV2.leadsV3
                st['vis'] = float(ld[0].x[0]) if len(ld) and len(ld[0].x) else 0.0
            elif w == 'radarState':
                l1 = m.radarState.leadOne
                st['dRel'], st['vRel'], st['vLead'] = float(l1.dRel), float(l1.vRel), float(l1.vLead)
            elif w == 'longitudinalPlan':
                st['aTgt'] = float(m.longitudinalPlan.aTarget)
            elif w == 'carState':
                cs = m.carState
                st['vEgo'] = float(cs.vEgo); st['std'] = 1 if cs.standstill else 0
                st['en'] = 1 if cs.cruiseState.enabled else 0
                tt = float(m.logMonoTime) / 1e9
                print(f"{seg[-3:]}\t{tt:.1f}\t{st['idx2']}\t{st['idx128']}\t{st['vis']:.2f}\t{st['dRel']:.2f}\t"
                      f"{st['vRel']:.2f}\t{st['vLead']:.2f}\t{st['aTgt']:.3f}\t{st['vEgo']:.2f}\t{st['std']}\t"
                      f"{st['st05']}\t{st['en']}\t{st['res2']}\t{st['res128']}\t{st['res2']}\t{n2}\t{n128}\t"
                      f"{st['tgt']:.1f}\t{st['prim']}\t{st['obj']}\t{st['zl']}\t{st['loes']}\t{st['anh']}", file=out)
    except Exception as e:
        print(f'[warn] {seg}: {e}', file=sys.stderr)
    print(f"{seg[-3:]}\t{n2}\t{n128}\t{ntgt}\t{n2}\t{n128}", file=cnt)
out.close(); cnt.close()
print('DONE', pre)
