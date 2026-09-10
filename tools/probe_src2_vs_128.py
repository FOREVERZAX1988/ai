#!/usr/bin/env python3
"""0071/0072: 同一帧内 ACC_02(0x30C) 在 src=2(RX bus2,原厂) vs src=128(OP代发回环) 的 idx/ZL 差异，
并与视觉 dRel / 旧表 / 新公式交叉对照。"""
import sys, glob, json, collections
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/openpilot")
import numpy as np
from openpilot.tools.lib.logreader import LogReader

IDX_TAB = np.array(json.load(open('/data/openpilot/ai/tools/abstands_idx_table.json')))
T_TAB = np.array(json.load(open('/data/openpilot/ai/tools/abstands_t_table.json')))
def t_old(i): return float(np.interp(i, IDX_TAB, T_TAB))
def t_new(i):
    if i < 100: return 0.8
    if i > 560: return 6.0
    return 0.008718 * i + 1.0178

def run(rt, segs=3):
    fs = sorted(glob.glob(f'/data/media/0/realdata/{rt}--*/rlog.zst'))[:segs]
    out = collections.defaultdict(list)
    for f in fs:
        st = {'r2': None, 'z2': None, 'r128': None, 'z128': None, 'r130': None, 'z130': None,
              'vis': None, 'vp': 0.0, 've': None, 'vw': None, 't': 0.0}
        for m in LogReader(f):
            w = m.which()
            if w == 'can':
                for c in m.can:
                    if c.address == 0x30C and len(c.dat) >= 7:
                        idx = ((c.dat[3] | (c.dat[4] << 8)) & 0x3FF)
                        zl = int((c.dat[4] >> 5) & 7)
                        d = c.dat
                        if c.src == 2: st['r2'], st['z2'] = idx, zl
                        elif c.src == 128: st['r128'], st['z128'] = idx, zl
                        elif c.src == 130: st['r130'], st['z130'] = idx, zl
                    elif c.address == 0x103 and len(c.dat) >= 8:
                        dd = c.dat
                        s = (((dd[2] | (dd[3] << 8)) & 0xFFF) + (((dd[3] >> 4) | (dd[4] << 4)) & 0xFFF) +
                             ((dd[5] | (dd[6] << 8)) & 0xFFF) + (((dd[6] >> 4) | (dd[7] << 4)) & 0xFFF)) * 0.1
                        st['vw'] = s / 4 / 3.6
            elif w == 'modelV2':
                ld = m.modelV2.leadsV3
                if len(ld) > 0 and len(ld[0].x) > 0:
                    st['vis'] = float(ld[0].x[0]); st['vp'] = float(ld[0].prob)
            elif w == 'carState':
                if st['vis'] is not None and st['r2'] is not None and st['vp'] > 0.5:
                    v = st['vw'] if (st['vw'] and st['vw'] > 1.0) else float(m.carState.vEgo)
                    if v > 1.0:
                        out['v'].append(v); out['vis'].append(st['vis'])
                        out['r2'].append(st['r2']); out['z2'].append(st['z2'])
                        out['r128'].append(st['r128'] if st['r128'] is not None else np.nan)
                        out['z128'].append(st['z128'] if st['z128'] is not None else np.nan)
    return {k: np.array(v) for k, v in out.items()}

for rt in ['00000071', '00000072']:
    d = run(rt)
    r2, r128, v, vis = d['r2'], d['r128'], d['v'], d['vis']
    ok = np.isfinite(r128)
    print(f"\n=== {rt}  n={len(r2)} (同时有 src128 的 n={ok.sum()}) ===")
    print(f" idx  src2 中位={np.median(r2):.0f}   src128 中位={np.nanmedian(r128):.0f}   "
          f"相等占比={np.mean(r2 == r128)*100:.1f}%  (|Δ|>20 占比={np.nanmean(np.abs(r2-r128) > 20)*100:.1f}%)")
    print(f" ZL   src2 分布={collections.Counter(d['z2']).most_common(4)}")
    print(f" ZL   src128 分布={collections.Counter(d['z128'][ok]).most_common(4)}")
    d_old2 = np.array([t_old(i) for i in r2]) * np.maximum(v, 5)
    d_new2 = np.array([t_new(i) for i in r2]) * np.maximum(v, 5)
    e128 = np.where(ok, np.array([t_old(i) if np.isfinite(i) else np.nan for i in r128]) * np.maximum(v, 5) - vis, np.nan)
    print(f" d_vis 中位={np.median(vis):.1f}  d_old(idx@src2)={np.median(d_old2):.1f}  d_new(idx@src2)={np.median(d_new2):.1f}")
    print(f" vis-old(src2) 中位={np.median(vis-d_old2):+.1f}   vis-new(src2) 中位={np.median(vis-d_new2):+.1f}")
    if ok.sum() > 100:
        print(f" old(idx@src128)-vis 中位={np.nanmedian(e128):+.1f}  → src128 更接近视觉则说明代发帧=融合后口径")
