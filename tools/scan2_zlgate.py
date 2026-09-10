#!/usr/bin/env python3
"""按用户前提重扫：idx/ZL 严格取 src==2（bus2 原厂雷达域），并做
  (1) 时距口径 t = d_vis / max(v,5)（去掉速度 confound）
  (2) 按原厂 ZL(ACC_Gesetzte_Zeitluecke 来自 src=2) 分组
  (3) 前车速度门控：|v_lead_radar(ACC_04@0x324) - v_lead_vision| <= 1.0 m/s
输出 /data/openpilot/ai/tools/.scan2/<route>.npz + <route>.json
"""
import sys, glob, json, os
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/openpilot")
import numpy as np
from openpilot.tools.lib.logreader import LogReader

IDX_TAB = np.array(json.load(open('/data/openpilot/ai/tools/abstands_idx_table.json')))
T_TAB = np.array(json.load(open('/data/openpilot/ai/tools/abstands_t_table.json')))
def t_old(i): return float(np.interp(i, IDX_TAB, T_TAB))
def t_new_raw(i):
    if i < 100: return 0.8
    if i > 560: return 6.0
    return 0.008718 * i + 1.0178

def parse(f):
    st = {'idx': 0, 'zl': -1, 'vw': 0.0, 'vlr': np.nan,
          'dv': np.nan, 'p': 0.0, 'vv': np.nan}
    rows = []
    for m in LogReader(f):
        w = m.which()
        if w == 'can':
            for c in m.can:
                if c.src != 2:            # 只认 bus2 原厂域
                    continue
                if c.address == 0x30C and len(c.dat) >= 7:
                    d = c.dat
                    st['idx'] = (d[3] | (d[4] << 8)) & 0x3FF
                    st['zl'] = int((d[4] >> 5) & 7)
                elif c.address == 0x324 and len(c.dat) >= 7:
                    d = c.dat
                    v = ((d[5] | (d[6] << 8)) & 0x3FF) * 0.32   # km/h
                    st['vlr'] = v / 3.6 if v < 320 else np.nan   # m/s
        elif w == 'carState':
            if st['idx'] > 10 and np.isfinite(st['dv']):
                v = st['vw'] if st['vw'] > 1.0 else float(m.carState.vEgo)
                if v > 1.0 and st['p'] > 0.5:
                    rows.append((st['idx'], st['zl'], v, st['dv'], st['vlr'], st['vv']))
        elif w == 'modelV2':
            ld = m.modelV2.leadsV3
            if len(ld) > 0 and len(ld[0].x) > 0:
                st['dv'] = float(ld[0].x[0]); st['p'] = float(ld[0].prob)
                st['vv'] = float(ld[0].v[0]) if len(ld[0].v) > 0 else np.nan
    return rows

def summarize(rt, rows):
    a = np.array(rows, dtype=float)
    idx, zl, v, dv, vlr, vv = a.T
    tvis = dv / np.maximum(v, 5.0)
    told = np.array([t_old(i) for i in idx])
    tnew = np.array([t_new_raw(i) for i in idx])
    gate = np.isfinite(vlr) & np.isfinite(vv) & (np.abs(vlr - vv) <= 1.0)
    out = {'route': rt, 'n': int(len(a)), 'n_gate': int(gate.sum()),
           'v_kph': float(np.median(v) * 3.6), 'idx_med': float(np.median(idx)),
           'zl_dist': {int(k): int(c) for k, c in zip(*np.unique(zl, return_counts=True))},
           'zl_src': 'src2(bus2 stock)', 'by_zl': {}, 'fit': {}}
    for z in sorted(set(zl.astype(int))):
        m = zl == z
        if m.sum() < 300: continue
        out['by_zl'][str(z)] = {
            'n': int(m.sum()),
            'v_kph': float(np.median(v[m]) * 3.6),
            'idx_med': float(np.median(idx[m])),
            't_vis': float(np.median(tvis[m])), 't_old': float(np.median(told[m])), 't_new': float(np.median(tnew[m])),
            'dt_vis_old': float(np.median(tvis[m] - told[m])), 'dt_vis_new': float(np.median(tvis[m] - tnew[m])),
            'rel_vis_old%': float(np.median(np.abs(tvis[m] - told[m]) / np.maximum(told[m], .1)) * 100),
            'rel_vis_new%': float(np.median(np.abs(tvis[m] - tnew[m]) / np.maximum(tnew[m], .1)) * 100),
            'r_vis_old': float(np.corrcoef(idx[m][:200000], told[m][:200000])[0, 1] if m.sum() > 10 else np.nan),
            # 门控（前车速度一致）子集
            'gated_dt_vis_old': float(np.median((tvis - told)[m & gate])) if (m & gate).sum() > 100 else None,
            'gated_dt_vis_new': float(np.median((tvis - tnew)[m & gate])) if (m & gate).sum() > 100 else None,
        }
        # 线性拟合 t_vis ~ idx（视觉当真值，检验"是否整段平滑单公式"）
        mm = m & (idx > 100) & (idx < 560)
        if mm.sum() > 500:
            k, b = np.polyfit(idx[mm], tvis[mm], 1)
            out['fit'][str(z)] = {'slope': float(k), 'intercept': float(b), 'n': int(mm.sum()),
                                  'resid_by_idx_bin': {}}
            for lo in range(100, 560, 60):
                bb = mm & (idx >= lo) & (idx < lo + 60)
                if bb.sum() > 100:
                    out['fit'][str(z)]['resid_by_idx_bin'][f'{lo}-{lo+60}'] = float(
                        np.median(tvis[bb]) - (k * np.median(idx[bb]) + b))
    np.savez(f'/data/openpilot/ai/tools/.scan2/{rt}.npz', idx=idx, zl=zl, v=v, dv=dv, vlr=vlr, vv=vv, gate=gate)
    json.dump(out, open(f'/data/openpilot/ai/tools/.scan2/{rt}.json', 'w'), indent=1, ensure_ascii=False)
    return out

if __name__ == '__main__':
    routes = {}
    for f in sorted(glob.glob('/data/media/0/realdata/*--*/rlog.zst')):
        routes.setdefault(f.split('/')[-2].split('--')[0], []).append(f)
    want = sys.argv[1:] or ['00000002', '00000003', '00000004', '00000049', '00000071', '00000072']
    for rt in want:
        rows = []
        for i, f in enumerate(sorted(routes[rt])):
            try:
                r = parse(f); rows.extend(r)
                print(f'  .. {rt} seg{i} +{len(r)} total={len(rows)}', flush=True)
            except Exception as e: print(f'{rt} {f} ERR {e}', flush=True)
        if len(rows) < 200:
            print(f'{rt}: n={len(rows)} 跳过', flush=True); continue
        s = summarize(rt, rows)
        print(json.dumps(s, ensure_ascii=False), flush=True)
