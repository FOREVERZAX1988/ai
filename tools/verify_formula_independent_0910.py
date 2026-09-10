#!/usr/bin/env python3
"""独立验证 0910 v2：原厂雷达距离公式(旧153表 vs 新线性) + 视觉一致性
K1 雷达闭合: d_stock=t(idx)*v_ego; 真值 Delta d = Integral(v_lead_can - v_ego)dt  (物理恒等式)
K2 视觉闭合: d_vis;            真值 Delta d = Integral(v_vis    - v_ego)dt
K3 用户设想: |v_vis - v_lead_can| 一致帧下 d_vis vs d_stock
只保留 |Delta s| 足够大的窗口(有信号)。
"""
import sys, json, os
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/openpilot")
import numpy as np
from openpilot.tools.lib.logreader import LogReader

IDX_TAB = np.array(json.load(open('/data/openpilot/ai/tools/abstands_idx_table.json')))
T_TAB   = np.array(json.load(open('/data/openpilot/ai/tools/abstands_t_table.json')))
def t_old(idx): return float(np.interp(idx, IDX_TAB, T_TAB))
def t_new(idx):
    if idx < 100: return 0.8
    if idx > 560: return 6.0
    return 0.008718 * idx + 1.0178

def parse(f):
    rows = []; cur_idx = 0.0; cur_vlead = None; cur_vwh = 0.0
    vis_d = None; vis_v = None; vis_p = 0.0
    for m in LogReader(f):
        w = m.which()
        if w == 'can':
            for c in m.can:
                if c.address == 259 and len(c.dat) >= 8:
                    d = c.dat
                    s = (((d[2] | (d[3] << 8)) & 0xFFF) + (((d[3] >> 4) | (d[4] << 4)) & 0xFFF)
                         + ((d[5] | (d[6] << 8)) & 0xFFF) + (((d[6] >> 4) | (d[7] << 4)) & 0xFFF)) * 0.1
                    cur_vwh = s / 4 / 3.6
                elif c.src == 2 and c.address == 780 and len(c.dat) >= 7:
                    cur_idx = float((c.dat[3] | (c.dat[4] << 8)) & 0x3FF)
                elif c.src == 2 and c.address == 804 and len(c.dat) >= 7:
                    vl = ((c.dat[5] | (c.dat[6] << 8)) & 0x3FF) * 0.32
                    cur_vlead = None if vl >= 320 else vl / 3.6
        elif w == 'modelV2':
            ld = m.modelV2.leadsV3
            if len(ld) > 0 and len(ld[0].x) > 0:
                vis_p = float(ld[0].prob); vis_d = float(ld[0].x[0]); vis_v = float(ld[0].v[0])
        elif w == 'carState':
            ve = float(m.carState.vEgo)
            vuse = cur_vwh if cur_vwh > 1.0 else ve
            rows.append((m.logMonoTime / 1e9, cur_idx, vuse, cur_vlead, vis_d, vis_v, vis_p))
    return rows

def windows(rows, L=2.0, step=0.2):
    """滑动窗口 ~L 秒, 步进 step 秒"""
    out = []; n = len(rows); i = 0
    while i < n - 1:
        j = i
        while j < n - 1 and rows[j][0] - rows[i][0] < L:
            j += 1
        out.append((i, j))
        t_lim = rows[i][0] + step; i += 1
        while i < n - 1 and rows[i][0] < t_lim:
            i += 1
    return out

def closure(rows, veh_key='can', L=2.0, min_abs_ds=1.0):
    X = []; Yold = []; Ynew = []; Yvis = []; IDXB = []
    for i, j in windows(rows, L):
        t0, idx0, v0, vl0, vd0, vv0, vp0 = rows[i]
        t1, idx1, v1, vl1, vd1, vv1, vp1 = rows[j]
        dt = t1 - t0
        if dt < 0.8 * L or idx0 <= 10 or idx1 <= 10: continue
        ds = 0.0; ok = True
        for k in range(i, j):
            rk, rk1 = rows[k], rows[k + 1]
            sk  = (rk[3]  if veh_key == 'can' else rk[5])
            sk1 = (rk1[3] if veh_key == 'can' else rk1[5])
            if sk is None or sk1 is None: ok = False; break
            # --- 连续性过滤: 排除前车切换/切入/丢目标 ---
            if rk[1] <= 10 or rk1[1] <= 10: ok = False; break          # 丢目标
            if abs(rk1[1] - rk[1]) > 25: ok = False; break             # idx 单步跳变
            if abs(idx1 - idx0) > 160: ok = False; break               # 窗口内总跳变
            sap = (rk[3] if veh_key == 'can' else rk[5]); sap1 = (rk1[3] if veh_key == 'can' else rk1[5])
            if sap is not None and sap1 is not None and abs(sap1 - sap) > 1.5: ok = False; break
            ddt = rk1[0] - rk[0]
            ds += 0.5 * ((sk - rk[2]) + (sk1 - rk1[2])) * ddt
        if not ok: continue
        if abs(ds) < min_abs_ds: continue
        X.append(ds); IDXB.append((idx0 + idx1) / 2.0)
        Yold.append(t_old(idx1) * v1 - t_old(idx0) * v0)
        Ynew.append(t_new(idx1) * v1 - t_new(idx0) * v0)
        if vd0 is not None and vd1 is not None:
            Yvis.append(vd1 - vd0)
        else:
            Yvis.append(np.nan)
    return (np.array(X), np.array(Yold), np.array(Ynew), np.array(Yvis), np.array(IDXB))

def rep(tag, X, Y, IDXB, bands=None):
    m = ~np.isnan(Y)
    X, Y, IDXB = X[m], Y[m], IDXB[m]
    if len(X) < 30: print(f'  {tag}: 样本不足 n={len(X)}'); return
    ratio = Y / X
    print(f'  {tag}: n={len(X)}  median(dY/ds)={np.median(ratio):.3f}  mean={np.mean(ratio):.3f}  '
          f'median|res|={np.median(np.abs(Y - X)):.2f}m  rmse={np.sqrt(np.mean((Y - X) ** 2)):.2f}m')
    if bands:
        for lo, hi in bands:
            s = (IDXB >= lo) & (IDXB < hi)
            if s.sum() < 20: continue
            print(f'      idx{lo}-{hi:<4} n={int(s.sum()):>5}  median(dY/ds)={np.median(Y[s]/X[s]):.3f}  '
                  f'median|res|={np.median(np.abs(Y[s]-X[s])):.2f}m')

if __name__ == '__main__':
    specs = sys.argv[1:] or [f'00000004--915ebf086f--{s}' for s in ['19','20','21','22','23','24','25','26','27']]
    allrows = []
    for spec in specs:
        f = f'/data/media/0/realdata/{spec}/rlog.zst'
        if not os.path.exists(f): print(f'[skip] {spec}'); continue
        r = parse(f); print(f'[load] {spec} rows={len(r)}'); allrows.extend(r)
    bands = [(27,100),(100,200),(200,300),(300,400),(400,561),(561,1021)]
    print(f'\n总行数={len(allrows)}')
    print('\n=== K1 雷达闭合  Y=Delta d_stock , X=Integral(v_lead_can - v_ego)dt ===')
    X, Yo, Yn, Yv, Ib = closure(allrows, 'can')
    rep('旧153表  ', X, Yo, Ib, bands); rep('新线性公式', X, Yn, Ib, bands)
    print('\n=== K2 视觉闭合  Y=Delta d_vis , X=Integral(v_vis - v_ego)dt ===')
    Xv, _, _, Yvv, Ibv = closure(allrows, 'vis')
    rep('视觉 d_vis', Xv, Yvv, Ibv, bands)
