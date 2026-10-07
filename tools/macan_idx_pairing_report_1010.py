#!/usr/bin/env python3
"""配对实验结果汇总（读 cache_pairing_1010/*.npz，不再解析 rlog）

两种估计口径都给：
  (1) 距离域（主口径，单位 = 米，直接决定控制层 dRel 误差）：d = (a·idx + b)·v，特征 [idx·v, v]
  (2) 时距域（与既有文档可比）：t = a·idx + b，t_meas = (x0 − off)/v
参照表：B1 = macan_calib 现行 (0.008969, 0.332)。
"""
import glob, os, sys
import numpy as np

CACHE = "/data/openpilot/ai/tools/cache_pairing_1010"
B1 = (0.008969, 0.332)
BANDS = [(2, 4), (4, 8), (8, 15), (15, 30)]
OFF = 1.52


def load():
    segs = sorted(glob.glob(f"{CACHE}/*.npz"))
    segs = [s for s in segs if not s.endswith("pooled.npz")]
    A = {}
    for f in segs:
        z = np.load(f)
        for k in z.files:
            A.setdefault(k, []).append(z[k])
    A = {k: np.concatenate(v) for k, v in A.items()}
    A["nsrc"] = len(segs)
    return A


def fit_m(A, m, off=OFF):
    v, idx, d = A["v"][m], A["idx"][m], A["d"][m] - off
    X = np.stack([idx * v, v], axis=1)
    (a, b), *_ = np.linalg.lstsq(X, d, rcond=None)
    pred = a * idx * v + b * v
    rms = float(np.sqrt(np.mean((d - pred) ** 2)))
    rms_b1 = float(np.sqrt(np.mean((d - (B1[0] * idx + B1[1]) * v) ** 2)))
    ratio = float(np.median(pred / np.maximum(d, 1e-6)))
    return a, b, rms, rms_b1, ratio, int(m.sum())


def fit_t(A, m, off=OFF):
    t = (A["d"][m] - off) / A["v"][m]
    a, b = np.polyfit(A["idx"][m], t, 1)
    rms = float(np.sqrt(np.mean((t - (a * A["idx"][m] + b)) ** 2)))
    rms_b1 = float(np.sqrt(np.mean((t - (B1[0] * A["idx"][m] + B1[1])) ** 2)))
    return a, b, rms, rms_b1


def main():
    A = load()
    n = len(A["idx"])
    print(f"段数={A['nsrc']}  配对样本={n}  冻结帧(构建期已剔)={int(A['frozen'].sum())} "
          f"({100*A['frozen'].mean():.1f}%)  冻结帧 v 中位={np.median(A['v'][A['frozen']]) if A['frozen'].any() else -1:.2f} m/s")
    p = A["p"] > 0.5
    d_ok = np.isfinite(A["d"]) & (A["d"] > 1) & (A["d"] < 150)
    idx_ok = (A["idx"] > 10) & (A["idx"] < 1020)
    v = A["v"]
    steady = np.abs(A["vv"] - v) <= 0.5
    print("门统计：d_ok %.1f%%  idx_ok %.1f%%  稳态 %.1f%%  obj==1 %.1f%%" % (
        100 * (d_ok & p).mean(), 100 * idx_ok.mean(), 100 * (steady & p & d_ok).mean(),
        100 * (A["obj"] == 1).mean()))
    for name, m in (("v>=2 全部", p & d_ok & idx_ok & (v >= 2)),
                    ("v>=2 + 稳态", p & d_ok & idx_ok & (v >= 2) & steady),
                    ("v>=4 + 稳态", p & d_ok & idx_ok & (v >= 4) & steady),
                    ("v>=4 + 稳态 + obj==1", p & d_ok & idx_ok & (v >= 4) & steady & (A["obj"] == 1))):
        print(f"\n### {name}  n={int(m.sum())}")
        for zl in (3, 4, None):
            mm = m if zl is None else m & (A["zl"] == zl)
            if mm.sum() < 200:
                print(f"  zl={zl}: 样本不足 n={int(mm.sum())}")
                continue
            a, b, rms, rms_b1, ratio, nn = fit_m(A, mm)
            ta, tb, trms, trms_b1 = fit_t(A, mm)
            print(f"  zl={zl}: n={nn:6d} | 距离域 d=({a:.5f}·idx+{b:+.3f})·v  RMS={rms:.2f}m (B1 {rms_b1:.2f}m) 中位预测/实测={ratio:.3f}"
                  f" | 时距域 t={ta:.5f}·idx+{tb:+.3f} RMS={trms:.2f}s (B1 {trms_b1:.2f}s)")
    print("\n### 分速度带（v>=2 稳态，zl=4）")
    for lo, hi in BANDS:
        mm = p & d_ok & idx_ok & (v >= max(lo, 2)) & (v < hi) & steady & (A["zl"] == 4)
        if mm.sum() < 200:
            print(f"  v={lo}–{hi}: 样本不足 n={int(mm.sum())}")
            continue
        a, b, rms, rms_b1, ratio, nn = fit_m(A, mm)
        print(f"  v={lo:2d}–{hi:2d}: n={nn:5d}  d=({a:.5f}·idx+{b:+.3f})·v  RMS={rms:.2f}m (B1 {rms_b1:.2f}m) 比值={ratio:.3f}")
    print("\n### 参考系敏感性（v>=4 稳态, zl=4）：off=0 / 1.52 / 2.5")
    for off in (0.0, 1.52, 2.5):
        mm = p & d_ok & idx_ok & (v >= 4) & steady & (A["zl"] == 4)
        a, b, rms, rms_b1, ratio, nn = fit_m(A, mm, off)
        ta, tb, trms, trms_b1 = fit_t(A, mm, off)
        print(f"  off={off:4.2f}: a={a:.5f} b={b:+.3f} RMS={rms:.2f}m | t={ta:.5f}·idx+{tb:+.3f}")


if __name__ == "__main__":
    main()
