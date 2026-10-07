#!/usr/bin/env python3
"""低速域 idx 换算口径复核 v2（2026-10-09，自建专用解析，避免 macan_route_lib_0910 的字段错位）

⚠️ 注意 macan_route_lib_0910.parse_segment 的 npz 里 "d_vis"/"v_vis" 两个键与内容互换
   （FIELDS 顺序 vs rows 元组顺序不一致：键 d_vis 实际存的是前车速度、键 v_vis 存的是距离）。
   本脚本自行解析，字段名以内容为准，不依赖该库。

分析：
  A. 分速度带  t_meas = d_vis/v vs 现表 t_tab = 0.008969*idx + 0.332
  B. 静止/冻结域 idx↔d_vis 是否单调（静态标定可行性）
  C. closer-only 门（|Δ|<max(25%·d_vis,2.0) 且 d_idx<d_vis）对 floor=5.0/3.7/2.5/none 的采纳率
用法: python3 macan_lowspeed_probe_1009.py <seg> [...]
"""
import sys, os
import numpy as np
sys.path.insert(0, "/data/openpilot/openpilot"); sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

REALDATA = "/data/media/0/realdata"
CACHE = "/data/openpilot/ai/tools/cache_lowspeed_1009"
T_A, T_B = 0.008969, 0.332
FIELDS = ["t", "v_ego", "idx", "v_lead_can", "obj_rel", "d_vis", "v_vis", "p_vis", "d_fused", "fused_present"]


def t_tab(idx):
    return T_A * np.asarray(idx, dtype=float) + T_B


def parse(seg):
    cf = f"{CACHE}/{seg}.npz"
    if os.path.exists(cf):
        z = np.load(cf); return {k: z[k] for k in z.files}
    p = f"{REALDATA}/{seg}/rlog.zst"
    if not os.path.exists(p):
        return None
    os.makedirs(CACHE, exist_ok=True)
    idx = 0.0; vlead = np.nan; rel = np.nan
    md, mv, mp, mt = np.nan, np.nan, 0.0, -1e9
    fd, fp = np.nan, 0.0
    rows = []
    for m in LogReader(p):
        w = m.which()
        if w == "can":
            for c in m.can:
                if c.src != 2:            # 只看原厂 bus2，排除 OP 代发
                    continue
                d = c.dat
                if c.address == 780 and len(d) >= 8:      # ACC_02
                    idx = float((d[3] | (d[4] << 8)) & 0x3FF)
                    rel = float((d[5] >> 6) & 0x03)
                elif c.address == 804 and len(d) >= 8:    # ACC_04 Geschw_Zielfahrzeug
                    v = ((d[5] | (d[6] << 8)) & 0x3FF) * 0.32
                    vlead = np.nan if v >= 320 else v / 3.6
        elif w == "modelV2":
            ld = m.modelV2.leadsV3
            if len(ld) and len(ld[0].x):
                mp, md, mv, mt = float(ld[0].prob), float(ld[0].x[0]), float(ld[0].v[0]), m.logMonoTime / 1e9
        elif w == "radarState":
            rs = m.radarState
            fd, fp = float(rs.leadOne.dRel), float(rs.leadOne.present)
        elif w == "carState":
            t = m.logMonoTime / 1e9
            fresh = (t - mt) < 0.12        # 视觉点云新鲜度上限
            rows.append((t, float(m.carState.vEgo), idx, vlead, rel,
                         md if fresh else np.nan, mv if fresh else np.nan, mp if fresh else 0.0,
                         fd, fp))
    a = np.array(rows, dtype=np.float64)
    out = {k: a[:, i] for i, k in enumerate(FIELDS)}
    np.savez_compressed(cf, **out)
    return out


def frozen(R, vthr=2.0, quiet=0.5):
    t, idx, v = R["t"], R["idx"], R["v_ego"]
    out = np.zeros(len(t), dtype=bool); lc = t[0]; prev = None
    for i in range(len(t)):
        if prev is None or idx[i] != prev:
            lc = t[i]
        out[i] = (v[i] < vthr) and (t[i] - lc >= quiet)
        prev = idx[i]
    return out


def vision_ok(R):
    return (R["p_vis"] > 0.5) & np.isfinite(R["d_vis"]) & (R["d_vis"] > 1.0) & (R["d_vis"] < 150.0)


BANDS = [(0.3, 2.0), (2.0, 4.0), (4.0, 8.0), (8.0, 15.0), (15.0, 30.0)]


def main(segs):
    print("=== A. 分速度带：实测时距 t_meas=d_vis/v  vs  现表 t_tab(idx)（门: prob>0.5, 视觉前车速度与 vEgo 差<=0.5 m/s）===")
    print(f"{'seg':<24}|{'band':<8}|{'n':>6}|{'t_meas':>7}|{'t_tab':>6}|{'ratio':>6}|{'a':>9}|{'b':>7}|{'RMS':>6}|{'zl3/zl4':>9}")
    for seg in segs:
        R = parse(seg)
        if R is None:
            print(f"{seg:<24}| missing"); continue
        base = vision_ok(R) & (R["idx"] >= 1) & (R["idx"] <= 1020) & (R["v_ego"] > 0.3)
        for lo, hi in BANDS:
            m = base & (R["v_ego"] >= lo) & (R["v_ego"] < hi) & \
                (np.isfinite(R["v_vis"]) & (np.abs(R["v_vis"] - R["v_ego"]) <= 0.5))
            if m.sum() < 30:
                continue
            tm = R["d_vis"][m] / R["v_ego"][m]; tt = t_tab(R["idx"][m])
            a, b = np.polyfit(R["idx"][m], tm, 1)
            rms = float(np.sqrt(np.mean((a * R["idx"][m] + b - tm) ** 2)))
            print(f"{seg:<24}|{f'{lo}-{hi}':<8}|{m.sum():>6}|{np.median(tm):>7.2f}|{np.median(tt):>6.2f}|"
                  f"{np.median(tm)/np.median(tt):>6.2f}|{a:>9.5f}|{b:>7.3f}|{rms:>6.2f}|{'':>9}")

    print("\n=== B. 静止/冻结域（v<2 且 idx 静默>=0.5s）：idx 能否当静态距离标定 ===")
    print(f"{'seg':<24}|{'t(s)':>8}|{'v':>5}|{'idx':>5}|{'d_vis':>7}|{'d@5':>6}|{'d@3.7':>7}|{'d@v':>6}|{'误差@5':>8}")
    for seg in segs:
        R = parse(seg)
        if R is None:
            continue
        fm = frozen(R) & vision_ok(R)
        ii = np.where(fm)[0]; last = None
        for k in ii:
            if last is None or R["idx"][k] != R["idx"][last] or R["t"][k] - R["t"][last] > 2.0:
                tt = float(t_tab(R["idx"][k]))
                print(f"{seg:<24}|{R['t'][k]:>8.1f}|{R['v_ego'][k]:>5.2f}|{R['idx'][k]:>5.0f}|{R['d_vis'][k]:>7.2f}|"
                      f"{tt*5.0:>6.2f}|{tt*3.7:>7.2f}|{tt*R['v_ego'][k]:>6.2f}|{tt*5.0-R['d_vis'][k]:>+8.2f}")
                last = k

    print("\n=== C. closer-only 门对不同 floor 的采纳率（雷达只可改近）===")
    print(f"{'seg':<24}|{'域':<18}|{'floor':>6}|{'n':>6}|{'采纳':>5}|{'率':>7}|{'平均Δ':>7}")
    for seg in segs:
        R = parse(seg)
        if R is None:
            continue
        frz = frozen(R)
        for dom, dm in (("moving v>=3", vision_ok(R) & (R["v_ego"] >= 3.0)),
                        ("静止/冻结 v<2", vision_ok(R) & frz)):
            dm = dm & (R["idx"] >= 1) & (R["idx"] <= 1020) & np.isfinite(R["d_fused"])
            if dm.sum() < 10:
                continue
            tt = t_tab(R["idx"][dm])
            for floor in (5.0, 3.7, 2.5, None):
                eff = np.maximum(R["v_ego"][dm], floor if floor else 0.3)
                d_idx = tt * eff
                gate = np.abs(d_idx - R["d_vis"][dm]) < np.maximum(0.25 * R["d_vis"][dm], 2.0)
                ok = gate & (d_idx < R["d_vis"][dm])
                mad = float(np.mean(np.abs(d_idx[ok] - R["d_vis"][dm][ok]))) if ok.sum() else float("nan")
                print(f"{seg:<24}|{dom:<18}|{str(floor):>6}|{dm.sum():>6}|{ok.sum():>5}|{ok.mean():>7.1%}|{mad:>7.2f}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["00000091--98208e01cb--9"])
