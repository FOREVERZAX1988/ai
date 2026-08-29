#!/usr/bin/env python3
"""原厂 ACC_05 帧内 axG/verz/mom 关联性（0004 正常段）"""
import sys, glob, os
sys.path.insert(0, "/data/openpilot")
import numpy as np
from openpilot.tools.lib.logreader import LogReader
BASE = "/data/media/0/realdata"

def extract(dat, start, length):
    val = 0
    for i in range(length):
        pos = start - i
        b = pos // 8; bit = pos % 8
        v = (dat[b] >> (7 - bit)) & 1 if b < len(dat) else 0
        val = (val << 1) | v
    return val

rows = []
for sp in glob.glob(f"{BASE}/00000004--*--*/rlog.zst")[:8]:
    for m in LogReader(sp):
        if m.which() != 'can': continue
        for c in m.can:
            if c.address == 269 and c.src == 2:
                st = extract(c.dat, 57, 3)
                verz = extract(c.dat, 32, 11)*0.005 - 7.22
                mom = extract(c.dat, 16, 10)
                axg = extract(c.dat, 48, 9)*0.024 - 2.016
                fv = extract(c.dat, 13, 1)
                fm = extract(c.dat, 12, 1)
                if st in (3, 4):
                    rows.append((verz, mom, axg, fv, fm))
A = np.array(rows)
print(f"样本 {len(A)} 帧 (st=3/4)")
acc = A[A[:,4] == 1]
dec = A[(A[:,3] == 1) | (A[:,0] < -0.05)]
print(f"加速态(fm=1): {len(acc)} 帧 | 减速态(fv=1或verz<0): {len(dec)} 帧")
for name, X in [("加速态", acc), ("减速态", dec)]:
    if len(X) < 10: continue
    v, mo, ax = X[:,0], X[:,1], X[:,2]
    c1 = np.corrcoef(v, mo)[0,1]
    c2 = np.corrcoef(ax, mo)[0,1]
    c3 = np.corrcoef(v, ax)[0,1]
    print(f"{name}: corr(verz,mom)={c1:+.2f} corr(axG,mom)={c2:+.2f} corr(verz,axG)={c3:+.2f}")
    if name == "加速态" and len(X) > 20:
        k = np.linalg.lstsq(mo.reshape(-1,1), ax, rcond=None)[0][0]
        print(f"  加速态 axG ≈ {k:.4f} × mom")
if len(dec) > 20:
    k = np.linalg.lstsq(dec[:,0].reshape(-1,1), dec[:,2], rcond=None)[0][0]
    print(f"减速态 axG ≈ {k:.4f} × verz")
