#!/usr/bin/env python3
"""Macan 标定复核通用库 (0910)
- parse_segment(): 解析 rlog -> 逐帧数组, 带 npz 缓存(避免重复解析)
- 距离映射: t_old(153点表) / t_new(0909线性公式)
- closure(): 运动学闭合 Δd = ∫(v_lead_can - v_ego)dt (纯CAN, 与视觉/公式无关 = 独立真值)
用法:
  import sys; sys.path.insert(0,'/data/openpilot/ai/tools')
  from macan_route_lib_0910 import parse_segment, t_old, t_new
"""
import os, json, sys
import numpy as np

sys.path.insert(0, "/data/openpilot/openpilot")
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader   # noqa: E402

REALDATA = "/data/media/0/realdata"
CACHE = "/data/openpilot/ai/tools/cache_0910"
_TAB = json.load(open("/data/openpilot/ai/tools/abstands_t_table.json"))
_IDX_TAB = np.array(_TAB["idx"] if isinstance(_TAB, dict) else json.load(open("/data/openpilot/ai/tools/abstands_idx_table.json")))
try:
    _T_TAB = np.array(_TAB["t"])
except Exception:
    _T_TAB = np.array(json.load(open("/data/openpilot/ai/tools/abstands_t_table.json")))

FIELDS = ["t", "idx", "v_wheel", "v_lead", "v_vis", "d_vis", "p_vis", "zl_set", "obj_rel", "v_cruise", "a_ego", "gas", "brake", "vbz"]


def rl(seg):
    return f"{REALDATA}/{seg}/rlog.zst"


def t_old(idx):
    return float(np.interp(idx, _IDX_TAB, _T_TAB))


def t_new(idx):
    if idx < 100:
        return 0.8
    if idx > 560:
        return 6.0
    return 0.008718 * idx + 1.0178


def d_old(idx, v_ego):
    return t_old(idx) * max(v_ego, 5.0)


def d_new(idx, v_ego):
    return t_new(idx) * max(v_ego, 5.0)


def parse_segment(seg, use_cache=True):
    """返回 dict[str, np.ndarray]，逐 carState 帧采样 CAN/modelV2 最新值。"""
    cf = f"{CACHE}/{seg}.npz"
    if use_cache and os.path.exists(cf):
        z = np.load(cf)
        return {k: z[k] for k in z.files}
    if not os.path.exists(rl(seg)):
        return None
    rows = []
    cur = dict(v_wheel=0.0, idx=0.0, v_lead=np.nan, zl_set=np.nan, obj_rel=np.nan,
               v_cruise=np.nan, vbz=np.nan)
    vd = vv = np.nan
    vp = 0.0
    for m in LogReader(rl(seg)):
        w = m.which()
        if w == "can":
            for c in m.can:
                d = c.dat
                if c.address == 259 and len(d) >= 8:            # ESP_VL_Radgeschw 0x103
                    s = (((d[2] | (d[3] << 8)) & 0xFFF) + (((d[3] >> 4) | (d[4] << 4)) & 0xFFF)
                         + ((d[5] | (d[6] << 8)) & 0xFFF) + (((d[6] >> 4) | (d[7] << 4)) & 0xFFF)) * 0.1
                    cur["v_wheel"] = s / 4.0 / 3.6
                elif c.address == 780 and len(d) >= 8:          # ACC_02
                    cur["idx"] = float((d[3] | (d[4] << 8)) & 0x3FF)
                    cur["zl_set"] = float((d[4] >> 5) & 0x07)   # ACC_Gesetzte_Zeitluecke 37|3
                    cur["obj_rel"] = float((d[5] >> 6) & 0x03)  # ACC_Relevantes_Objekt 46|2
                    cur["v_cruise"] = ((d[1] | (d[2] << 8)) >> 4 & 0x3FF) * 0.32  # Wunschgeschw 12|10
                elif c.address == 804 and len(d) >= 8:          # ACC_04
                    v = ((d[5] | (d[6] << 8)) & 0x3FF) * 0.32   # Geschw_Zielfahrzeug 40|10 km/h
                    cur["v_lead"] = np.nan if v >= 320 else v / 3.6
                elif c.address == 265 and len(d) >= 8:          # ACC_01
                    cur["vbz"] = ((d[3] | (d[4] << 8)) >> 3 & 0x7FF) * 0.005 - 7.22  # Sollbeschl
        elif w == "modelV2":
            ld = m.modelV2.leadsV3
            if len(ld) > 0 and len(ld[0].x) > 0:
                vp = float(ld[0].prob)
                vd = float(ld[0].x[0])
                vv = float(ld[0].v[0])
        elif w == "carState":
            cs = m.carState
            rows.append((m.logMonoTime / 1e9, cur["idx"], cur["v_wheel"], cur["v_lead"],
                         vd, vv, vp, cur["zl_set"], cur["obj_rel"], cur["v_cruise"],
                         float(cs.aEgo), float(cs.gasPressed), float(cs.brakePressed), cur["vbz"]))
    a = np.array(rows, dtype=np.float64)
    out = {k: a[:, i] for i, k in enumerate(FIELDS)}
    if use_cache:
        np.savez_compressed(cf, **out)
    return out


def windows(rows_t, L=2.0, step=0.2):
    """滑动窗口索引对, 近似 L 秒, 步进 step 秒"""
    out, n, i = [], len(rows_t), 0
    while i < n - 1:
        j = i
        while j < n - 1 and rows_t[j] - rows_t[i] < L:
            j += 1
        out.append((i, j))
        lim = rows_t[i] + step
        i += 1
        while i < n - 1 and rows_t[i] < lim:
            i += 1
    return out


def closure(R, key="can", L=2.0, step=0.2, min_abs_ds=1.0, max_idx_step=25, max_idx_win=160, max_dv=1.5):
    """K1/K2 闭合: X=∫(v_src - v_ego)dt (独立真值) ; Y=Δd_old/Δd_new/Δd_vis
    key='can' -> v_src=ACC_Geschw_Zielfahrzeug ; key='vis' -> v_src=leadsV3[0].v
    连续性过滤: 排除丢目标/前车切换/切入(靠 idx 跳变与前车速跳变)
    """
    t = R["t"]; idx = R["idx"]; v = R["v_wheel"]; vl = R["v_lead"]; dv = R["d_vis"]; vv = R["v_vis"]
    src = vl if key == "can" else vv
    X, Yold, Ynew, Yvis, IDXB, T0 = [], [], [], [], [], []
    for i, j in windows(t, L, step):
        if t[j] - t[i] < 0.8 * L or idx[i] <= 10 or idx[j] <= 10:
            continue
        ds, ok = 0.0, True
        for k in range(i, j):
            s0, s1 = src[k], src[k + 1]
            if not np.isfinite(s0) or not np.isfinite(s1):
                ok = False; break
            if idx[k] <= 10 or idx[k + 1] <= 10:
                ok = False; break
            if abs(idx[k + 1] - idx[k]) > max_idx_step:
                ok = False; break
            if abs(s1 - s0) > max_dv:
                ok = False; break
            ds += 0.5 * ((s0 - v[k]) + (s1 - v[k + 1])) * (t[k + 1] - t[k])
        if not ok or abs(idx[j] - idx[i]) > max_idx_win or abs(ds) < min_abs_ds:
            continue
        X.append(ds); IDXB.append(0.5 * (idx[i] + idx[j])); T0.append(t[i])
        Yold.append(t_old(idx[j]) * max(v[j], 5.0) - t_old(idx[i]) * max(v[i], 5.0))
        Ynew.append(t_new(idx[j]) * max(v[j], 5.0) - t_new(idx[i]) * max(v[i], 5.0))
        Yvis.append(dv[j] - dv[i] if (np.isfinite(dv[i]) and np.isfinite(dv[j])) else np.nan)
    return dict(X=np.array(X), Yold=np.array(Yold), Ynew=np.array(Ynew), Yvis=np.array(Yvis),
                IDX=np.array(IDXB), T0=np.array(T0))
