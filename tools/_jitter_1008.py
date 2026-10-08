#!/usr/bin/env python3
"""视觉抖动 vs 融合抑制：d_vis 短时大幅下跳(疑似视觉浮动)时，融合输出是否被平滑抑制。"""
import numpy as np
import sys
sys.path.insert(0, "/data/openpilot/ai/tools")

ROUTE = "00000092--d83e53a0c7"
CACHE = "/data/openpilot/ai/tools/cache_drive_1008"


def load(seg):
    z = np.load(f"{CACHE}/{seg}.npz", allow_pickle=True)
    return {k: z[k] for k in z.files}


tot = 0
jit = 0
jit_dec = 0
jit_fus_dec = 0
dvis_drops = []
dfus_drops = []
for i in range(1, 16):
    seg = f"{ROUTE}--{i}"
    r = load(seg)
    m = (r["enabled"] > 0.5) & (r["rpres"] > 0.5) & (r["mprob"] >= 0.5) & np.isfinite(r["d_vis"]) & (r["d_vis"] > 3)
    idx = np.where(m)[0]
    if len(idx) < 5:
        continue
    dv = r["d_vis"]
    df = r["d_fus"]
    vrel = r["mv"] - r["vEgo"]
    ac = r["accel_pl"]
    for k in range(2, len(idx)):
        a, b = idx[k - 2], idx[k]
        if b - a > 3:
            continue
        tot += 1
        drop = dv[a] - dv[b]
        if drop > 5.0 and vrel[b] > -1.0:      # 视觉自己掉 >5m 且前车没在逼近
            jit += 1
            fd = df[a] - df[b]
            dvis_drops.append(drop)
            if np.isfinite(fd):
                dfus_drops.append(fd)
            if ac[b] < -0.3:
                jit_dec += 1
                if np.isfinite(fd) and fd < 1.0:
                    jit_fus_dec += 1

print(f"评估帧 {tot}")
print(f"视觉短时下跳>5m 且 vRel>-1 (疑似视觉浮动): {jit} 帧 ({100*jit/max(tot,1):.2f}%)")
if dvis_drops:
    print(f"  视觉下跳幅度 mean={np.mean(dvis_drops):.1f} median={np.median(dvis_drops):.1f} max={np.max(dvis_drops):.1f} m")
    print(f"  同窗融合下跳 mean={np.mean(dfus_drops):.1f} median={np.median(dfus_drops):.1f} max={np.max(dfus_drops):.1f} m")
    print(f"  其中指令减速 {jit_dec} 帧；且融合确实跟着掉>1m 的 {jit_fus_dec} 帧 "
          f"(即未被平滑抑制的比例 {100*jit_fus_dec/max(jit,1):.1f}%)")
