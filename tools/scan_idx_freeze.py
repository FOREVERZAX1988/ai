#!/usr/bin/env python3
"""统计原厂 ACC(idx) 冻结事件: 有效 idx 连续保持同一数值 >= min_dur 秒的片段.
输出每次冻结: 时长 / 保持值 / 期间 vEgo 范围 / 期间 vLead 范围 / 期间视觉 dRel 变化(若有 modelV2)
用法: python3 scan_idx_freeze.py 0000007b [min_dur] [seg1,seg2]
"""
import glob, os, sys
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader

BASE = '/data/media/0/realdata'
PREFIX = sys.argv[1] if len(sys.argv) > 1 else '0000007b'
MIN_DUR = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
SEGSPEC = sys.argv[3] if len(sys.argv) > 3 else ''


def scan(f, tag):
    idx = 0.0
    vlead = None
    rows = []   # (t, idx, vEgo, vlead, dvis)
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
            rows.append([m.logMonoTime / 1e9, idx, float(m.carState.vEgo), vlead, None])
        elif w == 'modelV2':
            try:
                leads = m.modelV2.leadsV3
                if len(leads) > 0 and len(leads[0].x) > 0 and leads[0].prob > 0.5:
                    for r in rows[-20:]:
                        r[4] = float(leads[0].x[0])
            except Exception:
                pass
    runs = []
    cur = None
    for r in rows:
        t, ix, v, vl, dv = r
        valid = 0.0 < ix < 1021.0
        if valid and cur is not None and ix == cur['idx']:
            cur['n'] += 1
            cur['t1'] = t
            cur['v'].append(v)
            if vl is not None:
                cur['vl'].append(vl)
            if dv is not None:
                cur['dv'].append(dv)
        else:
            if cur is not None:
                runs.append(cur)
            cur = {'idx': ix, 't0': t, 't1': t, 'n': 1, 'v': [v],
                   'vl': [] if vl is None else [vl], 'dv': [] if dv is None else [dv],
                   'valid': valid} if valid else None
    if cur is not None:
        runs.append(cur)
    for c in runs:
        dur = c['t1'] - c['t0']
        if dur < MIN_DUR:
            continue
        vv = c['v']
        dvs = c['dv']
        dstr = f" dvis_span={max(dvs)-min(dvs):.1f}m" if len(dvs) > 1 else ""
        vlstr = f" vLead={min(c['vl']):.2f}..{max(c['vl']):.2f}" if c['vl'] else ""
        print(f"{tag} FROZEN idx={c['idx']:.0f} t={c['t0']:.1f} dur={dur:4.1f}s "
              f"vEgo={min(vv):.2f}..{max(vv):.2f}{vlstr}{dstr}")


segs = sorted(glob.glob(f'{BASE}/{PREFIX}--*/rlog.zst'),
              key=lambda p: int(p.split('--')[-1].split('/')[0]))
if SEGSPEC:
    keep = set(SEGSPEC.split(','))
    segs = [s for s in segs if s.split('--')[-1].split('/')[0] in keep]
print(f"{PREFIX}: {len(segs)} segs  min_dur={MIN_DUR}s")
for s in segs:
    tag = os.path.basename(os.path.dirname(s))
    try:
        scan(s, tag)
    except Exception as e:
        print(f"{tag} ERR {e}")
