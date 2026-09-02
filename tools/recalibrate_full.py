#!/usr/bin/env python3
"""ACC_Abstandsindex 全量重标定（6 route，2026-09-02，v2段级隔离）
拟合：全部route每route前10段；验证：每route最后2段(留出)。
每段在子进程读取，40s超时隔离(异常段kill跳过)，逐段flush进度。
分箱宽5：n>=30 用 median((d-1.0)/v)；n<30 继承原11点表插值(防噪声箱)。
对比：原11点表 / 纯加密表 / 混合表v2，分区间+总体中位相对误差。
用法: python3 ai/tools/recalibrate_full.py
"""
import glob, statistics, sys
from collections import defaultdict
from multiprocessing import Process, Queue

ROUTES = ["00000002", "00000003", "00000004", "00000049", "00000065", "00000066"]
N_FIT, N_VAL, SEG_TIMEOUT = 10, 2, 40

OLD_IDX = [100, 106, 122, 168, 234, 271, 363, 380, 389, 401, 420]
OLD_T   = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 6.0]

def interp_old(x):
    if x <= OLD_IDX[0]: return OLD_T[0]
    if x >= OLD_IDX[-1]: return OLD_T[-1]
    for i in range(len(OLD_IDX)-1):
        if OLD_IDX[i] <= x <= OLD_IDX[i+1]:
            return OLD_T[i] + (OLD_T[i+1]-OLD_T[i])*(x-OLD_IDX[i])/(OLD_IDX[i+1]-OLD_IDX[i])
    return OLD_T[-1]

def read_seg(f, q):
    from openpilot.tools.lib.logreader import LogReader
    out = []
    cur_idx = cur_v = cur_prob = 0.0
    cur_d = None
    for m in LogReader(f):
        w = m.which()
        if w == 'can':
            for c in m.can:
                if c.src != 2 or c.address != 780 or len(c.dat) < 7: continue
                cur_idx = (c.dat[3] | (c.dat[4] << 8)) & 0x3FF
        elif w == 'carState':
            cur_v = float(m.carState.vEgo)
        elif w == 'modelV2':
            try:
                ld = m.modelV2.leadsV3
                if len(ld) > 0:
                    cur_prob = float(ld[0].prob)
                    cur_d = float(ld[0].x[0]) if len(ld[0].x) > 0 else None
                else: cur_prob = 0.0; cur_d = None
            except Exception: cur_prob = 0.0; cur_d = None
            if cur_idx and 0 < cur_idx < 1021 and cur_prob > 0.5 and cur_d and 2.0 < cur_d < 300.0 and cur_v > 2.0:
                out.append((int(cur_idx), cur_v, cur_d))
    q.put(out)

def read_seg_safe(f):
    q = Queue()
    p = Process(target=read_seg, args=(f, q), daemon=True)
    p.start(); p.join(SEG_TIMEOUT)
    if p.is_alive():
        p.terminate(); p.join()
        print(f"  !! 段超时跳过: {f.split('/')[-2]}", flush=True)
        return []
    try:
        return q.get(timeout=5)
    except Exception:
        return []

fit, val = [], []
for r in ROUTES:
    fs = sorted(glob.glob(f'/data/media/0/realdata/{r}--*--*/rlog.zst'))
    for f in fs[:N_FIT]:
        fit += read_seg_safe(f)
        print(f"  FIT {r} {f.split('/')[-2]} ({len(fit)}样本)", flush=True)
    for f in fs[-N_VAL:]:
        val += read_seg_safe(f)
        print(f"  VAL {r} {f.split('/')[-2]} ({len(val)}样本)", flush=True)
print(f"\n拟合集={len(fit)} 验证集={len(val)}", flush=True)

by_bin = defaultdict(list)
for idx, v, d in fit: by_bin[idx//5].append((v, d))
pure, mixed = [], []
n_ok = 0
for b in sorted(by_bin):
    ss = by_bin[b]
    t = statistics.median((d-1.0)/v for v, d in ss)
    if t < 0: t = 0.0
    pure.append((b*5+2, round(t, 3)))
    if len(ss) >= 30:
        n_ok += 1
        mixed.append((b*5+2, round(t, 3)))
    else:
        mixed.append((b*5+2, round(interp_old(b*5+2), 3)))
print(f"箱数={len(pure)} 实测可靠箱(n>=30)={n_ok}", flush=True)

def interp_table(tbl, x):
    xs = [p[0] for p in tbl]; ys = [p[1] for p in tbl]
    if x <= xs[0]: return ys[0]
    if x >= xs[-1]: return ys[-1]
    for i in range(len(xs)-1):
        if xs[i] <= x <= xs[i+1]:
            return ys[i] + (ys[i+1]-ys[i])*(x-xs[i])/(xs[i+1]-xs[i])
    return ys[-1]

def median_rel_err(tbl, lo=None, hi=None):
    errs = []
    for idx, v, d in val:
        if lo is not None and idx < lo: continue
        if hi is not None and idx >= hi: continue
        t = interp_table(tbl, idx)
        d_pred = t * max(v, 5.0); d_ref = d - 1.0
        if d_ref > 2: errs.append(abs(d_pred-d_ref)/d_ref)
    return statistics.median(errs) if errs else -1

tbl_old = list(zip(OLD_IDX, OLD_T))
tables = [("原11点表", tbl_old), ("纯加密表", pure), ("混合表v2", mixed)]
print(f"\n{'表':<10} {'低速<234':>10} {'高速>=234':>10} {'全部':>8}", flush=True)
res = {}
for name, tbl in tables:
    e1 = median_rel_err(tbl, None, 234)
    e2 = median_rel_err(tbl, 234, None)
    e3 = median_rel_err(tbl)
    res[name] = e3
    print(f"{name:<10} {e1*100:9.2f}% {e2*100:9.2f}% {e3*100:7.2f}%", flush=True)

best = min(res, key=res.get)
print(f"\n>>> 总体最优: {best} ({res[best]*100:.2f}%)", flush=True)
if best != "原11点表":
    chosen = dict(tables)[best]
    print("\n=== 选定表内容（idx↔时距秒） ===")
    print("_macan_abstands_idx = [", ", ".join(str(p[0]) for p in chosen), "]")
    print("_macan_abstands_t   = [", ", ".join(str(p[1]) for p in chosen), "]")
