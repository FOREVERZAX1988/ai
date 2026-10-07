#!/usr/bin/env python3
"""原厂 ACC SnG 蠕行段逐 0.5s 时间线：idx 冻结期间车是否仍在蠕行靠近前车？
列: t_rel vEgo idx vLead(cluster) cam_x0 prob d_frozen(t*5) d_frozen(t*v)
用法: probe_stock_sng_timeline.py 0000007a 6,7
"""
import glob, sys
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader
BASE = '/data/media/0/realdata'
A, B, CAMS = 0.008969, 0.332, 1.52

pref = sys.argv[1]
segs = sys.argv[2].split(',')
for seg in segs:
    f = glob.glob(f'{BASE}/{pref}--*/rlog.zst')
    f = [p for p in f if p.split('--')[-1].split('/')[0] == seg]
    if not f: print('no seg', seg); continue
    idx = 0.0; vlead = None; x0 = None; prob = None
    rows = []
    t0 = None
    for m in LogReader(f[0]):
        t = m.logMonoTime/1e9
        w = m.which()
        if w == 'can':
            for c in m.can:
                if c.src != 2 or len(c.dat) < 7: continue
                if c.address == 780:
                    idx = float((c.dat[3] | (c.dat[4] << 8)) & 0x3FF)
                elif c.address == 0x324:
                    vl = (c.dat[5] | ((c.dat[6] & 0x03) << 8)) * 0.32
                    vlead = None if vl >= 320 else vl/3.6
        elif w == 'carState':
            rows.append([t, float(m.carState.vEgo), idx, vlead, x0, prob])
        elif w == 'modelV2':
            try:
                ld = m.modelV2.leadsV3
                if len(ld) > 0 and len(ld[0].x) > 0:
                    x0 = float(ld[0].x[0]); prob = float(ld[0].prob)
            except Exception: pass
    if not rows: continue
    t0 = rows[0][0]
    print(f'===== {pref} seg{seg}  ({len(rows)} samples) =====')
    nextp = 0.0
    for r in rows:
        t, v, ix, vl, x, p = r
        rel = t - t0
        if rel < nextp: continue
        nextp += 0.5
        t_gap = A*ix + B if 1 <= ix <= 1020 else None
        d5 = t_gap*max(v, 5.0) if t_gap else None
        dv = t_gap*v if t_gap else None
        print(f'  t={rel:7.2f} v={v:5.2f} idx={ix:4.0f} vLead={("%5.2f" % vl) if vl is not None else "  n/a"} '
              f'cam_x0={("%6.2f" % (x-CAMS)) if x is not None else "   n/a"} prob={("%.2f" % p) if p is not None else "n/a"} '
              f'| d_frozen(t*5)={("%6.2f" % d5) if d5 else "  n/a"} d(t*v)={("%6.2f" % dv) if dv else "  n/a"}')
