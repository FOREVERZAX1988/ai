#!/usr/bin/env python3
"""无车巡航振荡验证：vEgo 是否在 vSet 附近来回穿越（速度闭环极限环）？
指标：vEgo-vSet 过零次数、aTarget 正负交替次数、振荡周期、幅度
窗口：无车（lead>60m）+ 中高速巡航（v>15m/s）+ 连续300帧"""
import glob, sys
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

segs = sorted(glob.glob("/data/media/0/realdata/0000004f--*/rlog.zst"))
print("方法：窗口内统计 vEgo-vSet 过零（|dv|>0.3才计数，滤噪声）+ aTarget 正负交替")
print("如果过零频繁（每分钟>3次）→ 速度闭环振荡实锤（'一会加速一会减速'的机制）\n")

total_wins = 0
osc_wins = 0
for si in range(15):
    lr = LogReader(segs[si])
    st = {"f": 0, "en": False, "v": 0.0, "vset": 0.0, "at": 0.0, "lead": 999.0}
    win = []  # (f, v, vset, at)
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            cs = msg.carState
            st["en"] = cs.cruiseState.enabled
            st["v"] = cs.vEgo
            st["vset"] = cs.cruiseState.speed
        elif msg.which() == "longitudinalPlan":
            st["at"] = msg.longitudinalPlan.aTarget
        elif msg.which() == "modelV2":
            if len(msg.modelV2.leadsV3) > 0:
                st["lead"] = msg.modelV2.leadsV3[0].x[0]
        # 无车巡航窗口
        if st["en"] and st["v"] > 15.0 and st["lead"] > 60.0 and f % 2 == 0:
            win.append((f, st["v"], st["vset"], st["at"]))
            if len(win) > 150: win.pop(0)
            if len(win) == 150:
                # 分析窗口（3s）：vEgo-vSet 过零 + aTarget 交替
                dv = [v - vs for _, v, vs, _ in win]
                ats = [a for _, _, _, a in win]
                # 过零（带死区0.3：|dv|>0.3 才翻转）
                crossings = 0
                sign = 0
                for d in dv:
                    s = 1 if d > 0.3 else (-1 if d < -0.3 else 0)
                    if s != 0 and s != sign:
                        if sign != 0:
                            crossings += 1
                        sign = s
                # aTarget 正负交替
                at_flip = sum(1 for i in range(1, len(ats)) if (ats[i] > 0.15) != (ats[i-1] > 0.15))
                vspan = (max(v for _, v, _, _ in win) - min(v for _, v, _, _ in win)) * 3.6
                if crossings >= 2 and at_flip >= 2:
                    osc_wins += 1
                    print(f"  段{si} 帧{win[0][0]:>6} 振荡: vEgo-vSet过零={crossings}次/3s aTarget交替={at_flip}次 v跨度={vspan:.1f}km/h vset={win[0][2]*3.6:.0f}km/h")
                total_wins += 1
                win = []
        st["f"] += 1
    del lr

print(f"\n无车巡航窗口总数: {total_wins}（3s窗口）| 振荡窗口: {osc_wins} ({100*osc_wins/max(total_wins,1):.1f}%)")
print("振荡窗口占比>20% → 循环加减速普遍存在（速度闭环极限环）")
