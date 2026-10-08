#!/usr/bin/env python3
"""2026-10-08 路试复盘（视觉主导 + 雷达只能改近）：解析 + 分析

解析阶段（--parse，慢，后台跑）：
  从 rlog 取 radarTracks(原厂 idx 换算点/A3) / modelV2.leadsV3(视觉) / radarState.leadOne(融合输出)
  / longitudinalPlan / selfdriveState / onroadEvents，qlog 取 carState，缓存 npz。
分析阶段（--analyze，快）：
  1) 行程概览 2) 事件 3) 原厂雷达真实贡献（扣除滤波滞后）4) 幽灵刹车探针 5) SnG 起步 6) 纵向执行
"""
import os
import sys
import numpy as np

sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader  # noqa: E402

BASE = "/data/media/0/realdata"
ROUTE = "00000092--d83e53a0c7"
CACHE = "/data/openpilot/ai/tools/cache_drive_1008"
RTOC = 1.52
DT, RC = 0.05, 0.5
RATE_MIN, RATE_VF = 1.0, 1.2
REL_GATE, MIN_GAP, VPROB = 0.25, 2.0, 0.5


def nearest(st, sv, t):
    if len(st) == 0:
        return np.full_like(t, np.nan)
    i = np.clip(np.searchsorted(st, t, side="right") - 1, 0, len(st) - 1)
    return sv[i]


def nearest_gap(st, sv, t, max_gap=0.12):
    """最近样本，但样本时间距目标超过 max_gap 视为缺失(NaN) —— 避免"保持值"伪装成冻结。"""
    if len(st) == 0:
        return np.full_like(t, np.nan)
    i = np.clip(np.searchsorted(st, t, side="right") - 1, 0, len(st) - 1)
    age = t - st[i]
    out = sv[i]
    out = np.where(age <= max_gap, out, np.nan)
    return out


def interp(st, sv, t):
    if len(st) < 2:
        return np.full_like(t, np.nan)
    return np.interp(t, st, sv)


def parse(seg):
    os.makedirs(CACHE, exist_ok=True)
    cf = f"{CACHE}/{seg}.npz"
    qp, rp = f"{BASE}/{seg}/qlog.zst", f"{BASE}/{seg}/rlog.zst"
    if not (os.path.exists(qp) and os.path.exists(rp)):
        return False
    if os.path.exists(cf):
        return True
    qt, qv, qa, qs = [], [], [], []
    for m in LogReader(qp):
        if m.which() == "carState":
            cs = m.carState
            qt.append(m.logMonoTime / 1e9)
            qv.append(cs.vEgo)
            qa.append(cs.aEgo)
            qs.append(1.0 if cs.standstill else 0.0)
    qt = np.array(qt)

    mt, mp, mx, mv = [], [], [], []
    rt, rpres, rdrel, rvrel, rvlead, rmprob = [], [], [], [], [], []
    kt, kd = [], []
    lt, lacc, lsrc = [], [], []
    st, sen = [], []
    ev = []
    for m in LogReader(rp):
        w = m.which()
        t = m.logMonoTime / 1e9
        if w == "modelV2":
            lv = m.modelV2.leadsV3
            if len(lv) > 0:
                mt.append(t)
                mp.append(float(lv[0].prob))
                mx.append(float(lv[0].x[0]))
                mv.append(float(lv[0].v[0]))
        elif w == "radarState":
            lo = m.radarState.leadOne
            rt.append(t)
            rpres.append(1.0 if lo.present else 0.0)
            rdrel.append(float(lo.dRel))
            rvrel.append(float(lo.vRel))
            rvlead.append(float(lo.vLead))
            rmprob.append(float(lo.modelProb))
        elif w == "radarTracks":
            pts = m.radarTracks.points
            if len(pts) > 0:
                kt.append(t)
                kd.append(float(min(p.dRel for p in pts)))
        elif w == "longitudinalPlan":
            lt.append(t)
            lacc.append(float(m.longitudinalPlan.accels[0]))
            try:
                lsrc.append(str(m.longitudinalPlan.longitudinalPlanSource))
            except Exception:
                lsrc.append("?")
        elif w == "selfdriveState":
            st.append(t)
            sen.append(1.0 if m.selfdriveState.enabled else 0.0)
        elif w == "onroadEvents":
            for e in m.onroadEvents:
                ev.append((float(t), str(e.name), int(e.enable)))

    T = np.array(mt)
    if len(T) == 0:
        return False
    d = dict(t=T, mprob=np.array(mp), mx=np.array(mx), mv=np.array(mv))
    d["d_vis"] = d["mx"] - RTOC
    d["rpres"] = nearest(np.array(rt), np.array(rpres), T)
    d["d_fus"] = nearest(np.array(rt), np.array(rdrel), T)
    d["v_rel_f"] = nearest(np.array(rt), np.array(rvrel), T)
    d["v_lead_f"] = nearest(np.array(rt), np.array(rvlead), T)
    d["mprob_r"] = nearest(np.array(rt), np.array(rmprob), T)
    d["d_stock"] = nearest_gap(np.array(kt), np.array(kd), T) if kt else np.full_like(T, np.nan)
    d["has_stock"] = np.isfinite(d["d_stock"])
    d["enabled"] = nearest(np.array(st), np.array(sen), T)
    d["accel_pl"] = interp(np.array(lt), np.array(lacc), T)
    d["src_pl"] = nearest(np.array(lt), np.array(lsrc), T)
    d["vEgo"] = interp(qt, np.array(qv), T)
    d["aEgo"] = interp(qt, np.array(qa), T)
    d["standstill"] = nearest(qt, np.array(qs), T)
    np.savez_compressed(cf, ev_t=np.array([e[0] for e in ev]),
                        ev_n=np.array([e[1] for e in ev]),
                        ev_e=np.array([e[2] for e in ev], int), **d)
    return True


def load(seg):
    cf = f"{CACHE}/{seg}.npz"
    if not os.path.exists(cf):
        return None
    z = np.load(cf, allow_pickle=True)
    return {k: z[k] for k in z.files}


def vision_only_ref(d_vis, v_ego):
    n = len(d_vis)
    out = np.full(n, np.nan)
    prev = None
    for i in range(n):
        x = d_vis[i]
        if not np.isfinite(x):
            out[i] = np.nan
            continue
        if prev is None:
            prev = x
        alpha = DT / (RC + DT)
        prev = prev + alpha * (x - prev)
        if i > 0 and np.isfinite(out[i - 1]):
            step = RATE_MIN + RATE_VF * max(v_ego[i], 0.0) * DT
            prev = float(np.clip(prev, out[i - 1] - step, out[i - 1] + step))
        out[i] = prev
    return out


def analyze(segs):
    R = [(s, load(s)) for s in segs]
    R = [(s, r) for s, r in R if r is not None]
    print(f"=== 2026-10-08 路试复盘 {ROUTE}  ({len(R)} segments) ===\n", flush=True)

    print("--- 1) 行程概览 ---")
    tot_dist = 0.0
    for s, r in R:
        dt = np.diff(r["t"])
        eng = r["enabled"] > 0.5
        dist = np.nansum(r["vEgo"] * np.concatenate([[DT], dt]))
        tot_dist += dist
        evn = len(r["ev_t"])
        print(f"  {s[-2:]:>2s} {len(r['t']):5d}f {r['t'][-1]-r['t'][0]:5.1f}s engage={100*eng.mean():5.1f}% "
              f"v[{np.nanmin(r['vEgo']):.1f},{np.nanmax(r['vEgo']):.1f}] {dist:5.0f}m ev={evn}")
    print(f"  合计里程 ~{tot_dist:.0f} m")

    print("\n--- 2) 事件汇总 (enable/disable) ---")
    evc = {}
    for s, r in R:
        for n, e in zip(r["ev_n"], r["ev_e"]):
            evc.setdefault(str(n), [0, 0])
            evc[str(n)][0 if e else 1] += 1
    for k, (a, b) in sorted(evc.items(), key=lambda x: -(x[1][0] + x[1][1])):
        print(f"  {k:42s} {a:5d} / {b:5d}")

    print("\n--- 3) 原厂雷达( idx→距离 )的真实贡献：actual - 纯视觉参考管线 ---")
    all_eff = []
    adopt_ok = 0
    adopt_seen = 0
    big = []
    for s, r in R:
        m = (r["enabled"] > 0.5) & (r["mprob"] >= VPROB) & (r["rpres"] > 0.5) & np.isfinite(r["d_vis"]) & (r["d_vis"] > 0.5) & (r["d_fus"] > 0.5)
        if m.sum() < 20:
            continue
        dv = r["d_vis"].copy()
        ref = vision_only_ref(dv, r["vEgo"])
        eff = ref - r["d_fus"]
        sel = m & np.isfinite(eff)
        eff_s = eff[sel]
        all_eff.append(eff_s)
        # 本帧「过门且更近」的原厂值（模拟融合层的采纳判据）
        stock = r["d_stock"]
        gate = np.maximum(REL_GATE * r["d_vis"], MIN_GAP)
        cand = sel & np.isfinite(stock) & (stock > 0) & (stock < r["d_vis"]) & ((r["d_vis"] - stock) <= gate)
        adopt_seen += int(cand.sum())
        adopt_ok += int((cand & (eff > 0.10)).sum())
        idx = np.where(sel & (eff > 0.75))[0]
        for i in idx:
            big.append((s, float(r["t"][i]), float(r["d_vis"][i]), float(r["d_stock"][i]),
                        float(r["d_fus"][i]), float(eff[i])))
    all_eff = np.concatenate(all_eff) if all_eff else np.array([0.0])
    print(f"  样本 {len(all_eff)} 帧")
    print(f"  雷达介入量 eff=纯视觉参考-actual: mean={all_eff.mean():+.3f} median={np.median(all_eff):+.3f} "
          f"p95={np.percentile(all_eff,95):+.3f} max={all_eff.max():+.3f}")
    print(f"  eff>0.5m 帧 {int((all_eff>0.5).sum())} ({100*np.mean(all_eff>0.5):.2f}%) ; "
          f"eff<-0.5m 帧 {int((all_eff<-0.5).sum())} ({100*np.mean(all_eff<-0.5):.2f}%)")
    print(f"  融合层判据『原厂更近且过门』样本 {adopt_seen} 帧，其中实际被拉近(>0.1m) {adopt_ok} 帧 "
          f"({100*adopt_ok/max(adopt_seen,1):.1f}%)")
    print(f"  最大介入 (eff>0.75m) 共 {len(big)} 帧，前 12：")
    for s, t, dv, dk, df, e in sorted(big, key=lambda x: -x[5])[:12]:
        print(f"    {s[-2:]} t={t:.1f} d_vis={dv:6.2f} d_stock={dk:6.2f} d_fus={df:6.2f} eff={e:+.2f}")

    print("\n--- 4) 幽灵刹车探针（engage & 指令减速<-0.6 & 视觉前车未逼近）---")
    cnt = 0
    for s, r in R:
        m = (r["enabled"] > 0.5) & np.isfinite(r["accel_pl"]) & (r["accel_pl"] < -0.6)
        if not m.any():
            continue
        vrel = r["mv"] - r["vEgo"]
        for i in np.where(m)[0]:
            if vrel[i] > -0.5 and (not np.isfinite(r["d_vis"][i]) or r["d_vis"][i] > 3.0):
                if cnt < 15:
                    print(f"    {s[-2:]} t={r['t'][i]:.1f} a_cmd={r['accel_pl'][i]:+.2f} aEgo={r['aEgo'][i]:+.2f} "
                          f"vEgo={r['vEgo'][i]:.1f} d_vis={r['d_vis'][i]:.1f} d_fus={r['d_fus'][i]:.1f} "
                          f"d_stock={r['d_stock'][i]:.1f} vrel={vrel[i]:+.2f}")
                cnt += 1
    print(f"  候选帧 {cnt}")

    print("\n--- 5) SnG：停车->起步 ---")
    n = 0
    for s, r in R:
        ss = r["standstill"]
        for i in np.where((ss[:-1] > 0.5) & (ss[1:] < 0.5))[0]:
            n += 1
            j = min(i + 40, len(r["t"]) - 1)
            print(f"    {s[-2:]} t={r['t'][i]:.1f} d_fus@go={r['d_fus'][i]:6.2f} d_vis@go={r['d_vis'][i]:6.2f} "
                  f"d_stock@go={r['d_stock'][i]:6.2f} vLead={r['v_lead_f'][i]:4.2f} d_fus@+2s={r['d_fus'][j]:6.2f}")
    print(f"  起步 {n} 次")

    print("\n--- 6) 低速(engage,vEgo<5) 最小融合车距 ---")
    mn = []
    for s, r in R:
        m = (r["enabled"] > 0.5) & (r["vEgo"] < 5) & (r["rpres"] > 0.5) & (r["d_fus"] > 0.1)
        if m.any():
            k = int(np.argmin(np.where(m, r["d_fus"], 1e9)))
            mn.append((s, float(r["t"][k]), float(r["d_fus"][k]), float(r["vEgo"][k])))
    for s, t, d, v in sorted(mn, key=lambda x: x[2])[:8]:
        print(f"    {s[-2:]} t={t:.1f} d_fus={d:.2f} vEgo={v:.2f}")

    print("\n--- 7) 纵向执行 ---")
    for s, r in R:
        m = (r["enabled"] > 0.5) & np.isfinite(r["accel_pl"])
        if m.sum() < 100:
            continue
        a, ae = r["accel_pl"][m], r["aEgo"][m]
        print(f"    {s[-2:]} a_cmd[{np.percentile(a,5):+.2f},{np.percentile(a,95):+.2f}] "
              f"med={np.median(a):+.2f}  aEgo[{np.percentile(ae,5):+.2f},{np.percentile(ae,95):+.2f}] "
              f"corr={np.corrcoef(a,ae)[0,1]:.3f}  jerk_p95={np.nanpercentile(np.abs(np.diff(ae)/DT),95):.2f}")

    print("\n--- 8) 纵向指令来源分布(engage) ---")
    sc = {}
    tot = 0
    for s, r in R:
        m = r["enabled"] > 0.5
        for v in r["src_pl"][m]:
            sc[str(v)] = sc.get(str(v), 0) + 1
            tot += 1
    for k, v in sorted(sc.items(), key=lambda x: -x[1]):
        print(f"    {k:28s} {v:6d}  {100*v/max(tot,1):5.1f}%")

    print("\n--- 9) 原厂 idx 冻结检测（d_stock 恒定 >=1.0s 且 vEgo<2）---")
    nfr = 0
    worst = []
    for s, r in R:
        ds = r["d_stock"]
        t = r["t"]
        i = 0
        n = len(t)
        while i < n:
            if not np.isfinite(ds[i]) or r["vEgo"][i] >= 2.0:
                i += 1
                continue
            j = i
            while (j + 1 < n and np.isfinite(ds[j + 1]) and abs(ds[j + 1] - ds[i]) < 1e-9
                   and r["vEgo"][j + 1] < 2.0 and (t[j + 1] - t[j]) < 0.2):
                j += 1
            dur = t[j] - t[i]
            if dur >= 1.0:
                nfr += 1
                seg_msk = (t >= t[i]) & (t <= t[j])
                # 冻结期间视觉是否给出更近的真实距离
                dv = r["d_vis"][seg_msk]
                vv = dv[np.isfinite(dv)]
                fu = r["d_fus"][seg_msk]
                fu = fu[np.isfinite(fu)]
                if len(vv):
                    worst.append((s, float(t[i]), dur, float(ds[i]), float(np.nanmin(vv)),
                                  float(np.nanmedian(vv)), float(np.nanmedian(fu)) if len(fu) else np.nan))
            i = j + 1
    print(f"    冻结段 {nfr} 次")
    for s, t0, dur, dk, dvmin, dvmed, fumed in sorted(worst, key=lambda x: -(x[3] - x[4]))[:12]:
        print(f"    {s[-2:]} t={t0:.1f} 冻结{dur:4.1f}s d_stock={dk:6.2f} 视觉min={dvmin:6.2f} med={dvmed:6.2f} "
              f"| 融合med={fumed:6.2f} → 冻结高估 {dk-dvmin:+6.2f} m, 融合相对冻结 {fumed-dk:+6.2f} m")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    segs = [f"{ROUTE}--{int(a)}" for a in args] if args else [f"{ROUTE}--{i}" for i in range(1, 16)]
    if "--parse" in sys.argv:
        for s in segs:
            print(f"parse {s}: {'ok' if parse(s) else 'MISS'}", flush=True)
    else:
        analyze(segs)
