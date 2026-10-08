#!/usr/bin/env python3
"""原厂 ACC routes: 静止/蠕行阶段 idx 是否仍在更新?
用法: python3 scan_idx_standstill_stockacc.py 0000007b [seg1,seg2,...]
输出: 每个 >=1s 静止窗口(vEgo<0.3 m/s) 的有效 idx 起止/极值/是否变化 + vLead, 以及蠕行段 idx 变化
"""
import glob, os, sys
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader
BASE = '/data/media/0/realdata'
PREFIX = sys.argv[1] if len(sys.argv) > 1 else '0000007b'
SEGSPEC = sys.argv[2] if len(sys.argv) > 2 else ''

STAT = 0.3
CREEP_LO, CREEP_HI = 0.3, 2.2


def scan(f, tag):
    idx = 0.0
    vlead = None
    rows = []          # (t, idx, vEgo, vlead)
    for m in LogReader(f):
        w = m.which()
        if w == 'can':
            for c in m.can:
                if c.src != 2 or len(c.dat) < 7:
                    continue
                if c.address == 780:
                    idx = float((c.dat[3] | (c.dat[4] << 8)) & 0x3FF)
                elif c.address == 0x324:
                    vl = (c.dat[5] | ((c.dat[6] & 0x03) << 8)) * 0.32
                    vlead = None if vl >= 320 else vl / 3.6
        elif w == 'carState':
            rows.append((m.logMonoTime / 1e9, idx, float(m.carState.vEgo), vlead))
    i = 0
    while i < len(rows):
        if rows[i][2] < STAT:
            j = i
            while j + 1 < len(rows) and rows[j + 1][2] < STAT:
                j += 1
            dur = rows[j][0] - rows[i][0]
            if dur >= 1.0:
                win = rows[i:j + 1]
                vi = [r[1] for r in win if 0.0 < r[1] < 1021.0]
                lead = [r[3] for r in win if r[3] is not None]
                ls = f"vLead={min(lead):.2f}..{max(lead):.2f}" if lead else "vLead=none"
                if vi:
                    print(f"{tag} STAT t={win[0][0]:.1f} dur={dur:4.1f}s valid_idx n={len(vi)}/{len(win)} "
                          f"first={vi[0]:.0f} last={vi[-1]:.0f} min={min(vi):.0f} max={max(vi):.0f} "
                          f"uniq={len(set(vi))} {'<<UPDATING' if len(set(vi)) > 1 else '(FROZEN)'} {ls}")
                else:
                    print(f"{tag} STAT t={win[0][0]:.1f} dur={dur:4.1f}s idx invalid all ({ls})")
            i = j + 1
        else:
            i += 1
    creep = [(t, ix, v) for t, ix, v, _ in rows if CREEP_LO <= v < CREEP_HI and 0.0 < ix < 1021.0]
    if creep:
        ix = [c[1] for c in creep]
        print(f"{tag} CREEP n={len(creep)} idx min={min(ix):.0f} max={max(ix):.0f} uniq={len(set(ix))} "
              f"v={min(c[2] for c in creep):.2f}..{max(c[2] for c in creep):.2f}")


segs = sorted(glob.glob(f'{BASE}/{PREFIX}--*/rlog.zst'),
              key=lambda p: int(p.split('--')[-1].split('/')[0]))
if SEGSPEC:
    keep = set(SEGSPEC.split(','))
    segs = [s for s in segs if s.split('--')[-1].split('/')[0] in keep]
print(f"{PREFIX}: {len(segs)} segs")
for s in segs:
    tag = os.path.basename(os.path.dirname(s))
    try:
        scan(s, tag)
    except Exception as e:
        print(f"{tag} ERR {e}")
