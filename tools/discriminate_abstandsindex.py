#!/usr/bin/env python3
"""判别 ACC_Abstandsindex 语义：距离指数 vs 时距指数（2026-09-02）
方法：同一idx在不同车速下——若 d(视觉lead距离) 稳定 → 距离模型 d=g(idx)；
      若 d/v（=时距秒）稳定 → 时距模型 d=t(idx)*v（当前实现）。
数据：00000002(城市低速)+00000004(高速) 原厂模式，prob>0.5 视觉lead可靠样本。
用法: python3 ai/tools/discriminate_abstandsindex.py
"""
import glob, statistics
from collections import defaultdict
from openpilot.tools.lib.logreader import LogReader

samples = defaultdict(list)  # idx -> [(v_ego, d_vis)]
cur_idx = cur_v = cur_prob = 0.0
cur_d = None

def process(f):
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
                    xy = ld[0].x
                    cur_d = float(ld[0].x[0]) if len(ld[0].x) > 0 else None
                else:
                    cur_prob = 0.0; cur_d = None
            except Exception:
                cur_prob = 0.0; cur_d = None
            # 采样：prob>0.5 且 idx 有效且速度>2m/s
            if cur_idx and 0 < cur_idx < 1021 and cur_prob > 0.5 and cur_d and 2.0 < cur_d < 300.0 and cur_v > 2.0:
                samples[int(cur_idx)].append((cur_v, cur_d))

routes = {
    "00000004(高速)": sorted(glob.glob('/data/media/0/realdata/00000004--*--*/rlog.zst'))[:10],
    "00000002(城市)": sorted(glob.glob('/data/media/0/realdata/00000002--*--*/rlog.zst'))[:10],
}
for name, fs in routes.items():
    for f in fs:
        process(f)
        print(f"  {name} {f.split('/')[-2]} 完成", flush=True)

print(f"\n=== 判别结果（CV=变异系数 std/mean，越小越稳定） ===")
print(f"{'idx':>5} {'n':>5} {'车速范围':>14} {'d均值(m)':>9} {'CV(d)':>6} {'CV(d/v)':>8}  判定")
t_win = d_win = 0
for idx in sorted(samples):
    vv = [s[0] for s in samples[idx]]
    dd = [s[1] for s in samples[idx]]
    tt = [d / v for (v, d) in samples[idx]]
    if len(dd) < 15:
        continue
    cv_d = statistics.pstdev(dd) / statistics.mean(dd)
    cv_t = statistics.pstdev(tt) / statistics.mean(tt)
    verdict = "时距(d/v稳)" if cv_t < cv_d * 0.8 else ("距离(d稳)" if cv_d < cv_t * 0.8 else "模糊")
    if verdict == "时距(d/v稳)": t_win += 1
    elif verdict == "距离(d稳)": d_win += 1
    print(f"{idx:5d} {len(dd):5d} {min(vv):6.1f}-{max(vv):6.1f} {statistics.mean(dd):9.1f} {cv_d:6.2f} {cv_t:8.2f}  {verdict}")
print(f"\n汇总: 时距更稳 {t_win} 个idx | 距离更稳 {d_win} 个idx")
