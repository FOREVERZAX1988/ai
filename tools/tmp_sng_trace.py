#!/usr/bin/env python3
"""SnG 起步溯源：逐帧 dump idx(bus2/bus128)/视觉dRel/planner aTarget/ACC状态/按键位。
用法: python3 tmp_sng_trace.py <route_prefix> [t0 t1]
"""
import sys, os
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader
BASE = '/data/media/0/realdata'
pre = sys.argv[1]
t0 = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
t1 = float(sys.argv[3]) if len(sys.argv) > 3 else 1e9
segs = sorted(d for d in os.listdir(BASE) if d.startswith(pre) and os.path.isfile(f'{BASE}/{d}/rlog.zst'))
out = open(f'/data/openpilot/ai/tools/_trace_{pre}.txt', 'w')
hdr = ("seg\tT\tidx2\tidx128\tvis_dRel\tradar\tdRel\tvRel\tvLead\taTgt\tvEgo\tstd\tacc05st\t"
       "cruiseEn\tcruiseV\tLS_res\tLS_set\tLS_spd+\tprimAnz\tzl\tbus128seen")
print(hdr, file=out)
for seg in segs:
    f = f'{BASE}/{seg}/rlog.zst'
    st = {'idx2': 0, 'idx128': 0, 'vis_d': 0.0, 'vis_p': 0.0, 'dRel': 0.0, 'vRel': 0.0,
          'vLead': 0.0, 'radar': -1, 'aTgt': 0.0, 'vEgo': 0.0, 'std': 0, 'acc05': -1, 'crEn': 0,
          'crV': 0.0, 'res2': 0, 'set2': 0, 'spd2': 0, 'res128': 0, 'prim': -1, 'zl': -1,
          'idx128_seen': 0, 'idx2_seen': 0}
    tt = 0.0
    try:
        for m in LogReader(f):
            w = m.which()
            if w == 'can':
                for c in m.can:
                    d = c.dat
                    if c.address == 780 and len(d) >= 7:
                        v = (d[3] | (d[4] << 8)) & 0x3FF
                        if c.src == 2:
                            st['idx2'] = v; st['idx2_seen'] = 1
                        elif c.src == 128:
                            st['idx128'] = v; st['idx128_seen'] = 1
                        st['prim'] = (d[5] >> 6) & 0x3
                        st['zl'] = (d[4] >> 5) & 7
                    elif c.address == 0x10b and len(d) >= 4:
                        b = int.from_bytes(d[:4], 'little')
                        if c.src == 2:
                            st['set2'] = (b >> 16) & 1; st['spd2'] = (b >> 17) & 1; st['res2'] = (b >> 19) & 1
                        elif c.src == 128:
                            st['res128'] = (b >> 19) & 1
                    elif c.address == 0x10d and c.src == 2 and len(d) >= 8:
                        b = int.from_bytes(d[:8], 'little')
                        st['acc05'] = (b >> 57) & 7
            elif w == 'modelV2':
                ld = m.modelV2.leadsV3
                if len(ld) > 0 and len(ld[0].x) > 0:
                    st['vis_p'] = float(ld[0].prob); st['vis_d'] = float(ld[0].x[0])
                else:
                    st['vis_p'] = 0.0; st['vis_d'] = 0.0
            elif w == 'radarState':
                ls = m.radarState.leadOne
                st['dRel'] = float(ls.dRel); st['vRel'] = float(ls.vRel); st['vLead'] = float(ls.vLead)
                st['radar'] = 1 if ls.radar else 0
            elif w == 'longitudinalPlan':
                st['aTgt'] = float(m.longitudinalPlan.aTarget)
            elif w == 'carState':
                cs = m.carState
                st['vEgo'] = float(cs.vEgo); st['std'] = 1 if cs.standstill else 0
                st['crEn'] = 1 if cs.cruiseState.enabled else 0
                st['crV'] = float(cs.cruiseState.speed)
                tt = float(m.logMonoTime) / 1e9
                if t0 <= tt <= t1:
                    print(f"{seg[-3:]}\t{tt:.1f}\t{st['idx2']}\t{st['idx128']}\t{st['vis_d']:.2f}\t{st['radar']}\t"
                          f"{st['dRel']:.2f}\t{st['vRel']:.2f}\t{st['vLead']:.2f}\t{st['aTgt']:.3f}\t"
                          f"{st['vEgo']:.2f}\t{st['std']}\t{st['acc05']}\t{st['crEn']}\t{st['crV']:.1f}\t"
                          f"{st['res2']}\t{st['set2']}\t{st['spd2']}\t{st['prim']}\t{st['zl']}\t"
                          f"{st['idx128_seen']}", file=out)
    except Exception as e:
        print(f'  [warn] {seg}: {e}', file=sys.stderr)
out.close()
print('DONE', pre)
