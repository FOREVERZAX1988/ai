#!/usr/bin/env python3
"""共同真值锚定：X = Integral(v_lead_can - v_ego)dt (原厂前车速度，独立于距离公式)
比较 Y: Delta d_old(旧153表) / Delta d_new(新线性) / Delta d_vis(视觉) 谁最接近物理真值。
只保留强相对运动 + 连续(无前车切换)窗口。"""
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

def closure_common(rows, L=2.0, min_abs_ds=1.0):
    X=[]; Yold=[]; Ynew=[]; Yvis=[]; IDXB=[]
    for i, j in windows(rows, L):
        t0, idx0, v0, vl0, vd0, vv0, vp0 = rows[i]
        t1, idx1, v1, vl1, vd1, vv1, vp1 = rows[j]
        dt = t1 - t0
        if dt < 0.8 * L or idx0 <= 10 or idx1 <= 10: continue
        ds = 0.0; ok = True
        for k in range(i, j):
            rk, rk1 = rows[k], rows[k+1]
            if rk[3] is None or rk1[3] is None: ok=False; break     # 无原厂前车速度
            if vd0 is None or vd1 is None: ok=False; break          # 无视觉
            if rk[1] <= 10 or rk1[1] <= 10: ok=False; break
            if abs(rk1[1]-rk[1]) > 25: ok=False; break
            if abs(idx1-idx0) > 160: ok=False; break
            if abs(rk1[3]-rk[3]) > 1.5: ok=False; break             # 前车速度跳变
            ddt = rk1[0]-rk[0]
            ds += 0.5*((rk[3]-rk[2]) + (rk1[3]-rk1[2]))*ddt
        if not ok or abs(ds) < min_abs_ds: continue
        X.append(ds); IDXB.append((idx0+idx1)/2.0)
        Yold.append(t_old(idx1)*v1 - t_old(idx0)*v0)
        Ynew.append(t_new(idx1)*v1 - t_new(idx0)*v0)
        Yvis.append(vd1 - vd0)
    return (np.array(X), np.array(Yold), np.array(Ynew), np.array(Yvis), np.array(IDXB))

def rep(tag, X, Y, IDXB, bands):
    m = ~np.isnan(Y); X,Y,I = X[m],Y[m],IDXB[m]
    if len(X) < 30: print(f'  {tag}: n<30'); return
    print(f'  {tag}: n={len(X):>5}  median(Δd/truth)={np.median(Y/X):.3f}  mean={np.mean(Y/X):.3f}  median|res|={np.median(np.abs(Y-X)):.2f}m')
    for lo,hi in bands:
        s=(I>=lo)&(I<hi)
        if s.sum()<20: continue
        print(f'      idx{lo}-{hi:<4} n={int(s.sum()):>5}  median={np.median(Y[s]/X[s]):.3f}  median|res|={np.median(np.abs(Y[s]-X[s])):.2f}m')

if __name__ == '__main__':
    specs = sys.argv[1:]
    allrows=[]
    for spec in specs:
        f=f'/data/media/0/realdata/{spec}/rlog.zst'
        if not os.path.exists(f): continue
        allrows.extend(parse(f))
    bands=[(27,100),(100,200),(200,300),(300,400),(400,561),(561,1021)]
    print(f'总行数={len(allrows)}')
    X,Yo,Yn,Yv,Ib = closure_common(allrows)
    print(f'\n=== 共同真值 X=∫(v_lead_can - v_ego)dt, n={len(X)} ===')
    rep('旧153表   ', X, Yo, Ib, bands)
    rep('新线性公式 ', X, Yn, Ib, bands)
    rep('视觉 d_vis ', X, Yv, Ib, bands)
