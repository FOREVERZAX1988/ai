#!/usr/bin/env python3
"""低速/静止段 idx -> 车距 候选公式对照 (原厂ACC routes)
地面真值 = modelV2.leadsV3[0].x[0] - 1.52 (prob>0.5 才算有效前车)
用法: python3 scan_idx_lowspeed_fit.py 0000007a,0000007b [vmax]
"""
import glob, os, sys
import numpy as np
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader

BASE = '/data/media/0/realdata'
PREFIXES = (sys.argv[1] if len(sys.argv) > 1 else '0000007a,0000007b').split(',')
VMAX = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
B1A, B1B = 0.008969, 0.332
CAMS = 1.52

samples = []   # (idx, vEgo, dvis, tag)
for pref in PREFIXES:
    for s in sorted(glob.glob(f'{BASE}/{pref}--*/rlog.zst'),
                    key=lambda p: int(p.split('--')[-1].split('/')[0])):
        tag = os.path.basename(os.path.dirname(s))
        idx = 0.0
        v = 0.0
        dvis = None
        try:
            for m in LogReader(s):
                w = m.which()
                if w == 'can':
                    for c in m.can:
                        if c.src == 2 and c.address == 780 and len(c.dat) >= 7:
                            idx = float((c.dat[3] | (c.dat[4] << 8)) & 0x3FF)
                elif w == 'carState':
                    v = float(m.carState.vEgo)
                elif w == 'modelV2':
                    try:
                        ld = m.modelV2.leadsV3
                        dvis = (float(ld[0].x[0]) - CAMS) if (len(ld) > 0 and len(ld[0].x) > 0 and ld[0].prob > 0.5) else None
                    except Exception:
                        dvis = None
                    if 0.0 < idx < 1021.0 and v < VMAX and dvis is not None and 0.5 < dvis < 50.0:
                        samples.append((idx, v, dvis, tag))
        except Exception as e:
            print(tag, 'ERR', e)

print(f"samples={len(samples)} (v<{VMAX} m/s, 视觉前车 prob>0.5)")
if not samples:
    sys.exit(0)
I = np.array([s[0] for s in samples]); V = np.array([s[1] for s in samples]); D = np.array([s[2] for s in samples])
STAT = V < 0.3
print(f"  all: v {V.min():.2f}..{V.max():.2f}  静止子集(v<0.3): n={STAT.sum()}  idx {I[STAT].min() if STAT.sum() else 0:.0f}..{I[STAT].max() if STAT.sum() else 0:.0f}")

def rep(name, Dc, mask=None):
    m = np.ones_like(D, bool) if mask is None else mask
    if m.sum() == 0:
        return
    e = Dc[m] - D[m]
    print(f"  {name:38s} n={m.sum():5d} 中位偏差={np.median(e):+6.2f}m  MAE={np.median(np.abs(e)):5.2f}m  |e|<=1m={100*np.mean(np.abs(e)<=1):4.1f}%")

for mask, tagm in ((None, "全部"), (V < 0.3, "静止"), (V >= 0.3, "蠕行0.3-2")):
    print(f"--- {tagm} (n={ (len(D) if mask is None else mask.sum()) }) ---")
    t = B1A * I + B1B
    rep("A) idx/30", I / 30.0, mask)
    rep("B) t(idx)*max(v,5)", t * np.maximum(V, 5.0), mask)
    rep("C) t(idx)*max(v,2)", t * np.maximum(V, 2.0), mask)
    rep("D) t(idx)*v  (v>0.3)", t * V, mask)
    # 线性最小二乘 d = a*idx + b (仅在子集上)
    mm = np.ones_like(D, bool) if mask is None else mask
    if mm.sum() > 30:
        a, b = np.polyfit(I[mm], D[mm], 1)
        rep(f"E) 拟合 {a:.5f}*idx {b:+.3f}", a * I + b, mask)
        print(f"      -> 拟合残差 RMS={np.sqrt(np.mean(((a*I+b-D)[mm])**2)):.2f}m")
