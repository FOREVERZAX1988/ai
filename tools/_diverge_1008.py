#!/usr/bin/env python3
"""量化：融合距离与视觉距离的背离，以及是否伴随指令减速（幽灵刹车嫌疑）。"""
import sys
import numpy as np
sys.path.insert(0, "/data/openpilot/ai/tools")

ROUTE = "00000092--d83e53a0c7"
CACHE = "/data/openpilot/ai/tools/cache_drive_1008"


def load(seg):
    z = np.load(f"{CACHE}/{seg}.npz", allow_pickle=True)
    return {k: z[k] for k in z.files}


rows = []
for i in range(1, 16):
    seg = f"{ROUTE}--{i}"
    r = load(seg)
    m = (r["enabled"] > 0.5) & (r["rpres"] > 0.5) & (r["mprob"] >= 0.5) & np.isfinite(r["d_vis"]) \
        & (r["d_vis"] > 0.5) & (r["d_fus"] > 0.5)
    if m.sum() == 0:
        continue
    dv = r["d_vis"][m]
    df = r["d_fus"][m]
    ac = r["accel_pl"][m]
    diff = df - dv
    big = np.abs(diff) > 5.0
    close = diff < -5.0      # 融合比视觉近 >5m
    far = diff > 5.0
    dec = ac < -0.3
    # 合法雷达采纳：原厂新鲜、更近、且过 25%/2m 门
    st = r["d_stock"][m]
    gate = np.maximum(0.25 * dv, 2.0)
    legit = np.isfinite(st) & (st > 0) & (st < dv) & ((dv - st) <= gate)
    arti = close & ~legit
    lg_close = close & legit
    rows.append((seg, int(m.sum()), float(np.median(diff)), int(big.sum()), int(close.sum()),
                 int(far.sum()), int((close & dec).sum()), int(dec.sum()),
                 int(lg_close.sum()), int(arti.sum()), int((arti & dec).sum())))
    # 打印背离最严重的时刻
    idx = np.where(m)[0]
    worst = idx[np.argsort(-np.abs(diff))[:3]]
    for k in worst:
        if abs(df[np.searchsorted(idx, k)] - dv[np.searchsorted(idx, k)]) > 8:
            j = np.searchsorted(idx, k)
            print(f"  {seg[-2:]} t={r['t'][k]:.2f} d_vis={dv[j]:6.2f} d_fus={df[j]:6.2f} "
                  f"a_cmd={ac[j]:+.2f} vEgo={r['vEgo'][k]:.1f}")

print(f"\n{'seg':>4s} {'n':>6s} {'medΔ':>7s} {'|Δ|>5':>6s} {'近>5':>6s} {'合法雷达':>7s} {'人为近>5':>7s} {'人为&减速':>8s}")
for s, n, md, big, close, far, cd, dec, lg, ar, ad in rows:
    print(f"{s[-2:]:>4s} {n:6d} {md:+7.2f} {big:6d} {close:6d} {lg:7d} {ar:7d} {ad:8d}")

tot = sum(r[1] for r in rows)
tot_close = sum(r[4] for r in rows)
tot_lg = sum(r[8] for r in rows)
tot_ar = sum(r[9] for r in rows)
tot_ad = sum(r[10] for r in rows)
print(f"\n合计: 样本 {tot}")
print(f"  融合比视觉近>5m : {tot_close} ({100*tot_close/tot:.2f}%)")
print(f"    其中 合法雷达采纳(过门): {tot_lg} ({100*tot_lg/max(tot_close,1):.1f}%)")
print(f"    其中 人为/滤波伪影    : {tot_ar} ({100*tot_ar/max(tot_close,1):.1f}%)  伴随指令减速 {tot_ad}")
