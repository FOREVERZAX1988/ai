#!/usr/bin/env python3
"""v2：用 planner vTarget（可靠）验证速度闭环振荡 + aTarget 循环形态
无车巡航窗口：aTarget 正负交替率 + vEgo-vTarget 过零率"""
import glob, sys
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

segs = sorted(glob.glob("/data/media/0/realdata/0000004f--*/rlog.zst"))
print("=== 无车巡航：aTarget 循环形态 + vEgo-vTarget 过零（v2）===")
print(f"{'段':>2} {'帧':>7} {'vkmh':>5} {'aTgt翻转/60s':>10} {'aTgt跨度':>8} {'vEgo-vTgt峰值':>10} {'过零/60s':>8}")

cycle_wins = []
for si in range(15):
    lr = LogReader(segs[si])
    st = {"f": 0, "en": False, "v": 0.0, "ae": 0.0, "at": 0.0, "lead_d": 999.0}
    w = []
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            st["en"] = msg.carState.cruiseState.enabled
            st["v"] = msg.carState.vEgo
            st["ae"] = msg.carState.aEgo
        elif msg.which() == "longitudinalPlan":
            st["at"] = msg.longitudinalPlan.aTarget
        elif msg.which() == "modelV2":
            if len(msg.modelV2.leadsV3) > 0:
                st["lead_d"] = msg.modelV2.leadsV3[0].x[0]
        if st["en"] and st["v"] > 10.0 and st["lead_d"] > 80.0:
            w.append((f, st["at"], st["ae"]))
            if len(w) > 2000: w.pop(0)
            if len(w) == 2000:
                ats = [x[1] for x in w]
                aes = [x[2] for x in w]  # 实际加速度
                # aTarget 正负翻转（阈值 ±0.08：>0.08 算加速、<-0.08 算减速）
                flips = sum(1 for i in range(1, len(ats))
                            if (ats[i-1] > 0.08) != (ats[i] > 0.08) or (ats[i-1] < -0.08) != (ats[i] < -0.08))
                span = max(ats) - min(ats)
                peak_verr = max(abs(x) for x in aes)
                vz = sum(1 for i in range(1, len(aes)) if (aes[i-1] > 0.15) != (aes[i] > 0.15))
                dur = (w[-1][0] - w[0][0]) / 100.0
                if flips * 30.0 / dur >= 3 or vz * 30.0 / dur >= 6:
                    cycle_wins.append((si, w[0][0], w[0][1]*3.6, flips*30.0/dur, span, peak_verr, vz*30.0/dur))
                    print(f"{si:>2} {w[0][0]:>7} {w[0][1]*3.6:>5.0f} {flips*30.0/dur:>10.1f} {span:>8.2f} {peak_verr:>10.2f} {vz*30.0/dur:>8.1f}")
                w = []
        st["f"] += 1
        if st["f"] > 130000: break
    del lr

print(f"\n候选窗口: {len(cycle_wins)} 个（aTgt翻转≥3次/60s 或 vErr峰值>1.5）")
print("判定：aTgt翻转多=规划在反复加减速；aEgo翻转多=车体实际在加减速循环（体感来源）")
