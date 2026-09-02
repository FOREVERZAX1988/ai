#!/usr/bin/env python3
"""ACC_Abstandsindex 重标定（加密表）——2026-09-02
采集：00000002(城市)/00000004(高速)/0066 原厂+OP模式，prob>0.5 视觉lead可靠样本
拟合：按idx分箱(宽5)，t=median((d-1.0)/v) [视觉系统性偏远~1m修正] 或不修正
验证：留出集(未参与拟合段)，对比 11点原表/新表修正/新表不修正 的中位相对误差
用法: python3 ai/tools/recalibrate_abstandsindex.py
输出: 三表验证指标 + 选定加密表(可直接替换 radar_interface.py/radard.py 的标定表)
"""
import glob, statistics
from collections import defaultdict
from openpilot.tools.lib.logreader import LogReader

# ---------- 采集 ----------
FIT_ROUTES = {
    "00000002": sorted(glob.glob('/data/media/0/realdata/00000002--*--*/rlog.zst'))[:5],
    "00000004": sorted(glob.glob('/data/media/0/realdata/00000004--*--*/rlog.zst'))[:10],
    "00000066": sorted(glob.glob('/data/media/0/realdata/00000066--*--*/rlog.zst'))[:10],
}
VAL_ROUTES = {
    "00000004": sorted(glob.glob('/data/media/0/realdata/00000004--*--*/rlog.zst'))[-5:],
    "00000066": sorted(glob.glob('/data/media/0/realdata/00000066--*--*/rlog.zst'))[-5:],
}

cur_idx = cur_v = cur_prob = 0.0
cur_d = None

def process(f, samples):
    global cur_idx, cur_v, cur_prob, cur_d
    for m in LogReader(f):
        w = m.which()
        if w == 'can':
            for c in m.can:
                if c.src != 2 or c.address != 780 or len(c.dat) < 7:
                    continue
                cur_idx = (c.dat[3] | (c.dat[4] << 8)) & 0x3FF
        elif w == 'carState':
            cur_v = float(m.carState.vEgo)
        elif w == 'modelV2':
            try:
                ld = m.modelV2.leadsV3
                if len(ld) > 0:
                    cur_prob = float(ld[0].prob)
                    cur_d = float(ld[0].x[0]) if len(ld[0].x) > 0 else None
                else:
                    cur_prob = 0.0; cur_d = None
            except Exception:
                cur_prob = 0.0; cur_d = None
            if cur_idx and 0 < cur_idx < 1021 and cur_prob > 0.5 and cur_d and 2.0 < cur_d < 300.0 and cur_v > 2.0:
                samples.append((int(cur_idx), cur_v, cur_d))

fit = []
for name, fs in FIT_ROUTES.items():
    for f in fs:
        process(f, fit)
        print(f"  拟合段 {name} {f.split('/')[-2]} 完成 ({len(fit)}样本)", flush=True)
print(f"\n拟合集样本: {len(fit)}")

# ---------- 拟合：分箱(宽5)取中位时距 ----------
by_bin = defaultdict(list)   # bin -> [(v,d)]
for idx, v, d in fit:
    by_bin[idx // 5].append((v, d))
bins = sorted(by_bin)
new_t_corr = []   # (idx中心, t) 视觉偏1m修正
new_t_raw = []    # (idx中心, t) 不修正
for b in bins:
    vs = [s[0] for s in by_bin[b]]
    ds = [s[1] for s in by_bin[b]]
    t_corr = statistics.median((d - 1.0) / v for v, d in by_bin[b])
    t_raw = statistics.median(d / v for v, d in by_bin[b])
    if t_corr < 0: t_corr = 0.0
    new_t_corr.append((b * 5 + 2, round(t_corr, 3)))
    new_t_raw.append((b * 5 + 2, round(t_raw, 3)))
print(f"加密表点数: 修正={len(new_t_corr)} 不修正={len(new_t_raw)}")

# 原11点表
OLD_IDX = [100, 106, 122, 168, 234, 271, 363, 380, 389, 401, 420]
OLD_T   = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 6.0]

def interp_table(tbl, x):
    xs = [p[0] for p in tbl]; ys = [p[1] for p in tbl]
    if x <= xs[0]: return ys[0]
    if x >= xs[-1]: return ys[-1]
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            return ys[i] + (ys[i + 1] - ys[i]) * (x - xs[i]) / (xs[i + 1] - xs[i])
    return ys[-1]

# ---------- 验证（留出集） ----------
val = []
for name, fs in VAL_ROUTES.items():
    for f in fs:
        process(f, val)
        print(f"  验证段 {name} {f.split('/')[-2]} 完成 ({len(val)}样本)", flush=True)
print(f"\n验证集样本: {len(val)}")

def median_rel_err(tbl):
    errs = []
    for idx, v, d in val:
        t = interp_table(tbl, idx)
        d_pred = t * max(v, 5.0)
        d_ref = d - 1.0  # 视觉偏1m修正作参照
        if d_ref > 2:
            errs.append(abs(d_pred - d_ref) / d_ref)
    return statistics.median(errs) if errs else -1

err_old = median_rel_err(list(zip(OLD_IDX, OLD_T)))
err_new_corr = median_rel_err(new_t_corr)
err_new_raw = median_rel_err(new_t_raw)
print(f"\n=== 验证结果（中位相对误差，留出集 {len(val)} 样本） ===")
print(f"11点原表:      {err_old*100:.2f}%")
print(f"加密表(修正1m): {err_new_corr*100:.2f}%")
print(f"加密表(不修正): {err_new_raw*100:.2f}%")

best = min([(err_old, "原11点表", zip(OLD_IDX, OLD_T)),
            (err_new_corr, "加密表(修正1m)", new_t_corr),
            (err_new_raw, "加密表(不修正)", new_t_raw)], key=lambda x: x[0])
print(f"\n>>> 选定: {best[1]}（中位相对误差 {best[0]*100:.2f}%）")
print("\n=== 选定表内容（idx↔时距秒，可直接替换） ===")
print("_macan_abstands_idx = [", ", ".join(str(p[0]) for p in best[2]), "]")
print("_macan_abstands_t   = [", ", ".join(str(p[1]) for p in best[2]), "]")
