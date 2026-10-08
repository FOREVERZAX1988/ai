#!/usr/bin/env python3
"""2026-10-08 路试复盘：00000092--d83e53a0c7（视觉主导 + 雷达只能改近 融合后首测）

输出：
  1) 行程概览（时长/里程/速度/接管/事件/故障）
  2) 融合行为：视觉 vs 融合 dRel、雷达「改近」介入频次与幅度、跳变
  3) 幽灵刹车探针：指令减速度出现但前车并未逼近的帧
  4) SnG：停车->起步事件、起步时车距、最小车距
  5) 纵向执行：指令加速度 vs 实际、前车 vLead 来源
用法：python3 _drive_review_1008.py [1..15 ...]
"""
import os
import sys
import numpy as np

sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader  # noqa: E402

BASE = "/data/media/0/realdata"
ROUTE = "00000092--d83e53a0c7"
RTOC = 1.52  # RADAR_TO_CAMERA


def nearest(st, sv, t):
    if len(st) == 0:
        return np.full_like(t, np.nan)
    i = np.clip(np.searchsorted(st, t, side="right") - 1, 0, len(st) - 1)
    return sv[i]


def interp(st, sv, t):
    if len(st) < 2:
        return np.full_like(t, np.nan)
    return np.interp(t, st, sv)


QLOG_FIELDS = ("vEgo", "aEgo", "gasPressed", "brakePressed", "standstill",
               "steeringAngleDeg", "vCruise", "vCruiseCluster", "steeringTorque")


def read_seg(seg):
    qp = f"{BASE}/{seg}/qlog.zst"
    rp = f"{BASE}/{seg}/rlog.zst"
    if not (os.path.exists(qp) and os.path.exists(rp)):
        return None
    qt, qs = [], {k: [] for k in QLOG_FIELDS}
    for m in LogReader(qp):
        if m.which() == "carState":
            cs = m.carState
            qt.append(m.logMonoTime / 1e9)
            for k in QLOG_FIELDS:
                v = getattr(cs, k, np.nan)
                qs[k].append(float(v) if not isinstance(v, bool) else float(v))
    qt = np.array(qt)
    qs = {k: np.array(v, float) for k, v in qs.items()}

    mt, mp, mx, mv = [], [], [], []
    rt, rpres, rdrel, rvrel, rvlead, rradar, rmprob = [], [], [], [], [], [], []
    lt, lacc, lstop = [], [], []
    st, sen, sstate = [], [], []
    ev, errs = [], []
    for m in LogReader(rp):
        w = m.which()
        t = m.logMonoTime / 1e9
        if w == "modelV2":
            try:
                lv = m.modelV2.leadsV3
            except Exception:
                lv = []
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
            rradar.append(1.0 if lo.radar else 0.0)
            rmprob.append(float(lo.modelProb))
        elif w == "longitudinalPlan":
            lt.append(t)
            lacc.append(float(m.longitudinalPlan.accels[0]))
            lstop.append(1.0 if m.longitudinalPlan.shouldStop else 0.0)
        elif w == "selfdriveState":
            st.append(t)
            sen.append(1.0 if m.selfdriveState.enabled else 0.0)
            sstate.append(0)
        elif w == "onroadEvents":
            for e in m.onroadEvents:
                ev.append((t, str(e.name), int(e.enable)))
        elif w == "errorLogMessage":
            errs.append((t, str(m.errorLogMessage)))

    T = np.array(mt)
    if len(T) == 0:
        return None
    out = dict(seg=seg, t=T)
    out["mprob"] = np.array(mp)
    out["mx"] = np.array(mx)
    out["mv"] = np.array(mv)
    out["d_vis"] = np.array(mx) - RTOC
    out["rpres"] = nearest(np.array(rt), np.array(rpres), T)
    out["d_fus"] = nearest(np.array(rt), np.array(rdrel), T)
    out["v_rel_f"] = nearest(np.array(rt), np.array(rvrel), T)
    out["v_lead_f"] = nearest(np.array(rt), np.array(rvlead), T)
    out["radar_f"] = nearest(np.array(rt), np.array(rradar), T)
    out["mprob_r"] = nearest(np.array(rt), np.array(rmprob), T)
    out["enabled"] = nearest(np.array(st), np.array(sen), T)
    out["state"] = nearest(np.array(st), np.array(sstate), T)
    out["accel_pl"] = interp(np.array(lt), np.array(lacc), T)
    out["should_stop"] = nearest(np.array(lt), np.array(lstop), T)
    for k in QLOG_FIELDS:
        out[k] = interp(qt, qs[k], T)
    out["events"] = ev
    out["errors"] = errs
    return out


def main(segs):
    print(f"=== 2026-10-08 路试复盘 {ROUTE} segs={segs[0]}..{segs[-1]} ===\n")
    allr = []
    for s in segs:
        r = read_seg(s)
        if r is None:
            print(f"[{s}] 读取失败/缺文件")
            continue
        allr.append(r)
        dt = np.diff(r["t"])
        eng = r["enabled"] > 0.5
        dist = np.nansum(r["vEgo"] * np.concatenate([[0.05], dt]))
        print(f"[{s}] {len(r['t']):5d}f {r['t'][-1]-r['t'][0]:6.1f}s "
              f"engage={100*eng.mean():5.1f}%  v[{np.nanmin(r['vEgo']):.1f},{np.nanmax(r['vEgo']):.1f}]m/s "
              f"dist={dist:6.0f}m  events={len(r['events'])} errs={len(r['errors'])}")
    if not allr:
        return

    evc = {}
    for r in allr:
        for t, name, en in r["events"]:
            evc.setdefault(name, [0, 0])
            evc[name][0 if en else 1] += 1
    print("\n--- 事件汇总 (name: enable/disable) ---")
    for k, (a, b) in sorted(evc.items(), key=lambda x: -(x[1][0] + x[1][1])):
        print(f"  {k:45s} {a:4d} / {b:4d}")

    errs = [(r["seg"], t, m) for r in allr for t, m in r["errors"]]
    if errs:
        print("\n--- 故障/错误 ---")
        for s, t, m in errs[:10]:
            print(f"  {s} {t:.1f} {m[:120]}")

    # ---- 融合行为 ----
    eng_frames = vis_frames = both = closer = 0
    deltas = []
    jumps = []
    for r in allr:
        m = (r["enabled"] > 0.5) & (r["rpres"] > 0.5) & (r["mprob"] >= 0.5) & np.isfinite(r["d_vis"]) & (r["d_vis"] > 0.5)
        eng_frames += int((r["enabled"] > 0.5).sum())
        vis_frames += int((m | ((r["enabled"] > 0.5) & (r["mprob"] >= 0.5))).sum())
        if m.sum() == 0:
            continue
        dv = r["d_vis"][m]
        df = r["d_fus"][m]
        both += len(dv)
        d = df - dv
        deltas.append(d)
        closer += int((d < -0.30).sum())
        dd = np.abs(np.diff(df))
        jj = dd > 3.0
        if jj.any():
            idx = np.where(m)[0][1:][jj]
            for i in idx:
                jumps.append((r["seg"], r["t"][i], float(r["d_fus"][i - 1]), float(r["d_fus"][i])))
    deltas = np.concatenate(deltas) if deltas else np.array([0.0])
    print(f"\n--- 融合行为（engage & 视觉可用 & 前车存在）---")
    print(f"  engage 帧 {eng_frames}, 视觉可用(prob>=.5)帧 {vis_frames}, 有前车帧 {both}")
    print(f"  融合 vs 视觉 Δ=d_fused-d_vis: mean={deltas.mean():+.3f} median={np.median(deltas):+.3f} "
          f"p5={np.percentile(deltas,5):+.3f} min={deltas.min():+.3f} max={deltas.max():+.3f}")
    print(f"  雷达『改近』(Δ<-0.30m) 帧 {closer} ({100.0*closer/max(both,1):.2f}%)")
    print(f"  融合 dRel 单帧跳变>3m 次数 {len(jumps)}")
    for s, t, a, b in jumps[:12]:
        print(f"    {s} t={t:.2f} {a:.2f} -> {b:.2f}")

    # ---- 幽灵刹车探针 ----
    print("\n--- 幽灵刹车探针（engage & 指令减速度 <-0.6 & 视觉前车未逼近 vRel>-0.5）---")
    cnt = 0
    for r in allr:
        m = (r["enabled"] > 0.5) & np.isfinite(r["accel_pl"]) & (r["accel_pl"] < -0.6)
        if not m.any():
            continue
        idx = np.where(m)[0]
        vrel_vis = r["mv"] - r["vEgo"]
        for i in idx:
            if vrel_vis[i] > -0.5 and (not np.isfinite(r["d_vis"][i]) or r["d_vis"][i] > 3.0):
                if cnt < 12:
                    print(f"    {r['seg']} t={r['t'][i]:.2f} a_cmd={r['accel_pl'][i]:+.2f} "
                          f"aEgo={r['aEgo'][i]:+.2f} vEgo={r['vEgo'][i]:.1f} "
                          f"d_vis={r['d_vis'][i]:.1f} d_fus={r['d_fus'][i]:.1f} vrel_vis={vrel_vis[i]:+.2f}")
                cnt += 1
    print(f"  候选帧数 {cnt}")

    # ---- SnG ----
    print("\n--- SnG：停车->起步 ---")
    n = 0
    for r in allr:
        ss = r["standstill"]
        tr = np.where((ss[:-1] > 0.5) & (ss[1:] < 0.5))[0]
        for i in tr:
            n += 1
            j = min(i + 40, len(r["t"]) - 1)
            print(f"    {r['seg']} 起步 t={r['t'][i]:.2f} d_fused@go={r['d_fus'][i]:.2f} "
                  f"d_vis@go={r['d_vis'][i]:.2f} vLead={r['v_lead_f'][i]:.2f} "
                  f"d_fused@+2s={r['d_fus'][j]:.2f}")
    print(f"  起步次数 {n}")

    # ---- 低速最小车距 ----
    print("\n--- 低速(engage, vEgo<5) 前车最小融合车距 ---")
    mn = []
    for r in allr:
        m = (r["enabled"] > 0.5) & (r["vEgo"] < 5) & (r["rpres"] > 0.5) & (r["d_fus"] > 0.1)
        if m.any():
            k = int(np.argmin(np.where(m, r["d_fus"], 1e9)))
            mn.append((r["seg"], r["t"][k], float(r["d_fus"][k]), float(r["vEgo"][k])))
    for s, t, d, v in sorted(mn, key=lambda x: x[2])[:8]:
        print(f"    {s} t={t:.2f} d_fused={d:.2f} vEgo={v:.2f}")

    # ---- 仪表显示 ----
    print("\n--- 仪表/巡航设定 (vCruise vs vCruiseCluster) ---")
    for r in allr:
        m = r["enabled"] > 0.5
        if m.sum() < 20:
            continue
        print(f"    {r['seg']} vCruise med={np.nanmedian(r['vCruise'][m]):.2f} "
              f"cluster med={np.nanmedian(r['vCruiseCluster'][m]):.2f} "
              f"cluster min={np.nanmin(r['vCruiseCluster'][m]):.2f}")

    # ---- 纵向执行统计 ----
    print("\n--- 纵向执行 ---")
    for r in allr:
        m = (r["enabled"] > 0.5) & np.isfinite(r["accel_pl"])
        if m.sum() < 50:
            continue
        a = r["accel_pl"][m]
        ae = r["aEgo"][m]
        print(f"    {r['seg']} a_cmd[{np.percentile(a,5):+.2f},{np.percentile(a,95):+.2f}] "
              f"aEgo[{np.percentile(ae,5):+.2f},{np.percentile(ae,95):+.2f}] "
              f"corr={np.corrcoef(a,ae)[0,1]:.3f} "
              f"gas%={100*np.mean(r['gasPressed'][m]>0):.0f} brake%={100*np.mean(r['brakePressed'][m]>0):.0f}")


if __name__ == "__main__":
    args = sys.argv[1:]
    segs = [f"{ROUTE}--{int(a)}" for a in args] if args else [f"{ROUTE}--{i}" for i in range(1, 16)]
    main(segs)
