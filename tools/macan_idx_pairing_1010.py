#!/usr/bin/env python3
"""同一帧「视觉距离 ↔ 原厂 idx」配对实验（待办 ①，2026-10-10）

动机：T3 的分速度带 / zl 分层回归结论建立在多 route pooled 样本上，但
  (a) 用的是 0x103 轮速推算 v，(b) 未剔除静止/冻结帧，(c) 未做"同目标"配对门。
本工具用**唯一标定源** macan_route_lib_0910 重做：同一 carState 帧同时取 视觉 x0 与 原厂 idx，
按 zl 与 v 带分层回归 t = a*idx + b，并显式统计被"冻结帧"排除的样本量。

用户硬约束：**冻结帧不得进入标定**（vEgo<2 m/s 且 idx 静默≥0.5 s）。冻结是原厂低速设计行为，
不是标定点；用它拟合出来的"表"会把 10.09 m 这类钉死值固化进标定（idx=188 那类样本）。
用法：python3 macan_idx_pairing_1010.py <seg> [seg...]
"""
import os, sys
import numpy as np

sys.path.insert(0, "/data/openpilot/ai/tools")
from macan_route_lib_0910 import parse_segment  # noqa: E402

CACHE = "/data/openpilot/ai/tools/cache_pairing_1010"
os.makedirs(CACHE, exist_ok=True)
T_A, T_B = 0.008969, 0.332          # 现行 B1 表（macan_calib）
CAM_OFFS = (0.0, 1.52)              # 参考系候选：x0 原值 / 减 RADAR_TO_CAMERA
BANDS = [(2, 4), (4, 8), (8, 15), (15, 30)]


def frozen_mask(R, vthr=2.0, quiet=0.5):
    t, idx, v = R["t"], R["idx"], R["v_ego"]
    last = np.empty(len(t))
    c = t[0] if len(t) else 0.0
    prev = None
    for i in range(len(t)):
        if prev is None or idx[i] != prev:
            c = t[i]
        last[i] = c
        prev = idx[i]
    return (v < vthr) & ((t - last) >= quiet)


def build(seg):
    cf = f"{CACHE}/{seg}.npz"
    if os.path.exists(cf):
        z = np.load(cf)
        return {k: z[k] for k in z.files}
    R = parse_segment(seg)
    if R is None:
        return None
    fr = frozen_mask(R)
    d, vv = R["d_vis"], R["v_vis"]
    changed = np.ones(len(d), bool)
    changed[1:] = (d[1:] != d[:-1]) | (vv[1:] != vv[:-1])      # modelV2 ~20Hz vs carState 100Hz 去重
    out = dict(t=R["t"], idx=R["idx"], v=R["v_ego"], d=d, vv=vv, p=R["p_vis"],
               zl=R["zl_set"], obj=R["obj_rel"], frozen=fr, changed=changed)
    np.savez_compressed(cf, **out)
    return out


def main(segs):
    print(f"[args] {len(segs)} segments: {segs[:3]} ... {segs[-2:]}")
    P = {k: [] for k in ("seg", "t", "idx", "v", "d", "vv", "p", "zl", "obj")}
    n_tot = n_frozen = 0
    for s in segs:
        B = build(s)
        if B is None:
            print(f"[skip] {s}")
            continue
        n_tot += len(B["t"]); n_frozen += int(B["frozen"].sum())
        m = B["changed"] & np.isfinite(B["d"]) & (B["p"] > 0.5) & (B["d"] > 1) & (B["d"] < 150) & (B["idx"] > 10) & (B["idx"] < 1020)
        for k in ("idx", "v", "d", "vv", "zl", "obj"):
            P[k].append(B[k][m])
        P["seg"].append(np.array([s] * int(m.sum())))
    A = {k: np.concatenate(v) for k, v in P.items() if v}
    print(f"总帧 {n_tot}，其中冻结帧(v<2 & idx静默≥0.5s) {n_frozen} ({100*n_frozen/max(n_tot,1):.1f}%)；配对候选 {len(A['idx'])}")

    v = A["v"]; idx = A["idx"]
    steady = np.abs(A["vv"] - v) <= 0.5
    moving = v >= 2.0
    for name, extra in (("moving(v>=2) 全部", moving),
                        ("moving + 稳态(|Δv|<=0.5)", moving & steady),
                        ("moving + 稳态 + 非冻结", moving & steady)):
        sel = extra
        print(f"\n### {name}: n={int(sel.sum())}  (冻结帧已在样本构建阶段剔除={n_frozen}帧)")
        for zl in (3, 4):
            m = sel & (A["zl"] == zl)
            if m.sum() < 200:
                print(f"  zl={zl}: 样本不足 n={int(m.sum())}")
                continue
            for off in CAM_OFFS:
                tm = (A["d"][m] - off) / v[m]
                a, b = np.polyfit(idx[m], tm, 1)
                rms = float(np.sqrt(np.mean((tm - (a * idx[m] + b)) ** 2)))
                tab = T_A * idx[m] + T_B
                rms_tab = float(np.sqrt(np.mean((tm - tab) ** 2)))
                print(f"  zl={zl} off={off:4.2f}: n={int(m.sum()):6d}  t={a:.5f}·idx+{b:.3f}  RMS={rms:.3f}s"
                      f" | vs B1 RMS={rms_tab:.3f}s  比值中位(实测/表)={np.median(tm)/np.median(tab):.3f}")
    print("\n### 分速度带（稳态、非冻结、zl=4，off=1.52）")
    for lo, hi in BANDS:
        m = (A["zl"] == 4) & steady & (v >= lo) & (v < hi)
        if m.sum() < 200:
            print(f"  v={lo}–{hi}: 样本不足 n={int(m.sum())}")
            continue
        tm = (A["d"][m] - 1.52) / v[m]
        a, b = np.polyfit(idx[m], tm, 1)
        tab = T_A * idx[m] + T_B
        print(f"  v={lo:2d}–{hi:2d} m/s: n={int(m.sum()):6d}  t={a:.5f}·idx+{b:.3f}"
              f"  RMS={np.sqrt(np.mean((tm-(a*idx[m]+b))**2)):.3f} | vs B1 RMS={np.sqrt(np.mean((tm-tab)**2)):.3f}"
              f"  比值中位={np.median(tm)/np.median(tab):.3f}")
    np.savez_compressed(f"{CACHE}/pooled.npz", **A)
    print(f"\npooled 样本已存 {CACHE}/pooled.npz")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        args = ["00000002--5284e8b7f1--45", "00000002--5284e8b7f1--55", "00000003--90d0ff2aae--3",
                "00000004--915ebf086f--9", "00000004--915ebf086f--25", "00000049--98208e01cb--15"]
    main(args)
