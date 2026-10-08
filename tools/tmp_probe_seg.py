#!/usr/bin/env python3
"""定点取证：单段 0x10b(267) 按键帧 与 0x10d(269) ACC_05 的 src/位 明细。
用法: python3 tmp_probe_seg.py ROUTE_SEG_DIR [t0 t1]
"""
import sys
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader
seg = sys.argv[1].rstrip('/')
t0 = float(sys.argv[2]); t1 = float(sys.argv[3])
tt = 0.0
keys = {}
tgt = 0.0
for m in LogReader(f'{seg}/rlog.zst'):
    w = m.which()
    if w == 'carState':
        tt = float(m.logMonoTime) / 1e9
    elif w == 'can':
        for c in m.can:
            if not (t0 <= tt <= t1):
                continue
            d = c.dat
            if c.address == 267 and len(d) >= 3:
                b = int.from_bytes(d[:4], 'little')
                if (b >> 19) & 1 or (b >> 16) & 1 or (b >> 20) & 3:
                    keys.setdefault(('10b', c.src, d.hex()), [tt, tt, 0])
                    k = ('10b', c.src, d.hex())
                    keys[k][1] = tt; keys[k][2] += 1
            elif c.address == 269 and len(d) >= 8:
                b = int.from_bytes(d[:8], 'little')
                loes = (b >> 43) & 1; anh = (b >> 62) & 1
                st = (b >> 57) & 7; mom = (b >> 16) & 0x3FF
                fv = (b >> 13) & 1; fm = (b >> 12) & 1
                if loes or anh or st in (6, 7) or mom > 60:
                    k = ('10d', c.src, f'st={st} loes={loes} anh={anh} mom={mom} fm={fm} fv={fv}',
                         round((tt - t0) / 5))
                    keys.setdefault(k, [tt, tt, 0])
                    keys[k][1] = tt; keys[k][2] += 1
for k, v in sorted(keys.items(), key=lambda kv: kv[1][0]):
    print(f'  {k[0]} src={k[1]} {k[2]:<70} {v[0]:.1f}-{v[1]:.1f}s  x{v[2]}')
