#!/usr/bin/env python3
"""全 route 扫描: 每 segment 的"独立标定功率"清单 (0910)
功率定义 = 通过连续性过滤、|∫(v_lead_can-v_ego)dt|>=阈值的 2s 窗口数
(运动学闭合需要真实相对运动才有信息量; 稳态跟车 = 零信息)
输出: scan_routes_0910.jsonl (逐段) + scan_routes_0910.log (进度)
"""
import os, sys, json, glob, time
import numpy as np
sys.path.insert(0, "/data/openpilot/ai/tools")
from macan_route_lib_0910 import parse_segment, closure, REALDATA

OUT = "/data/openpilot/ai/tools/scan_routes_0910.jsonl"
PREF = sys.argv[1:] or ["00000002", "00000003", "00000004", "00000049", "00000071", "00000072"]


def segs_of(pre):
    out = []
    for d in glob.glob(f"{REALDATA}/{pre}--*"):
        s = d.split("--")[-1]
        if s.isdigit() and os.path.exists(f"{d}/rlog.zst"):
            out.append((int(s), f"{os.path.basename(d)}"))
    return [n for _, n in sorted(out)]


def main():
    fh = open(OUT, "a")
    allsegs = [(p, s) for p in PREF for s in segs_of(p)]
    print(f"total segments = {len(allsegs)}", flush=True)
    t00 = time.time()
    for n, (pre, seg) in enumerate(allsegs, 1):
        try:
            R = parse_segment(seg)
            if R is None or len(R["t"]) < 100:
                continue
            v = R["v_wheel"] * 3.6
            idx = R["idx"]
            vl = R["v_lead"]
            lead = np.isfinite(vl)
            c2 = closure(R, "can", L=2.0, step=0.2, min_abs_ds=2.0)
            c5 = closure(R, "can", L=2.0, step=0.2, min_abs_ds=5.0)
            zl = R["zl_set"][np.isfinite(R["zl_set"])]
            zl_u = np.unique(zl).astype(int).tolist() if len(zl) else []
            dz = np.diff(R["zl_set"])
            switches = int((np.abs(dz) > 0.5).sum())
            # 停车且前方有目标
            stop = (v < 0.5) & lead
            stop_fr = int(stop.sum())
            rec = dict(seg=seg, pre=pre, frames=len(R["t"]), dur_s=round(float(R["t"][-1] - R["t"][0]), 1),
                       v_max=round(float(np.nanmax(v)), 1), v_med=round(float(np.nanmedian(v)), 1),
                       lead_pct=round(100.0 * lead.mean(), 1),
                       idx_p50=float(np.nanmedian(idx[lead])) if lead.any() else None,
                       idx_p05=float(np.nanpercentile(idx[lead], 5)) if lead.any() else None,
                       idx_p95=float(np.nanpercentile(idx[lead], 95)) if lead.any() else None,
                       zl=zl_u, zl_switch=switches,
                       stop_frames=stop_fr,
                       pow2=len(c2["X"]), pow5=len(c5["X"]),
                       ds_p50=round(float(np.median(np.abs(c2["X"]))), 2) if len(c2["X"]) else None,
                       ratio_old=round(float(np.median(c2["Yold"] / c2["X"])), 3) if len(c2["X"]) else None,
                       ratio_new=round(float(np.median(c2["Ynew"] / c2["X"])), 3) if len(c2["X"]) else None,
                       idxrange=[float(c2["IDX"].min()), float(c2["IDX"].max())] if len(c2["X"]) else None)
            fh.write(json.dumps(rec) + "\n"); fh.flush()
            print(f"[{n}/{len(allsegs)}] {seg} v_max={rec['v_max']:>5} pow2={rec['pow2']:>3} pow5={rec['pow5']:>3} "
                  f"r_old={rec['ratio_old']} r_new={rec['ratio_new']} zl={zl_u} stop={stop_fr}", flush=True)
        except Exception as e:
            print(f"[{n}/{len(allsegs)}] {seg} ERROR {type(e).__name__}: {e}", flush=True)
    print(f"DONE in {round(time.time()-t00,1)}s", flush=True)


if __name__ == "__main__":
    main()
