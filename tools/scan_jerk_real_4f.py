#!/usr/bin/env python3
"""实际jerk（车体ESP加速度微分）vs 规划jerk（longitudinalPlan.jerks）对比
目标：定位"规划平滑但体感突然"的执行断层——
如果规划jerk受限(≤1.6)但实际jerk大(>2.5)，问题在执行环节（力矩映射/变速箱/刹车响应）"""
import glob, sys, re
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

DBC = "opendbc_repo/opendbc/dbc/vw_mlb.dbc"
dbc_text = open(DBC, encoding="latin-1").read()
def sig_def(name, msg_id):
    m = re.search(rf'^ SG_ {name} : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)', dbc_text, re.M)
    if not m: return None
    return (int(m.group(1)), int(m.group(2)), m.group(4)=='-', float(m.group(5)), float(m.group(6)))
ESPL = sig_def("ESP_Laengsbeschl", 257)
def get_sig(dat, start, length, signed):
    if len(dat) <= (start + length - 1) // 8: return 0
    val = 0
    for i in range(length):
        byte = (start + i) // 8
        bit = (start + i) % 8
        if dat[byte] & (1 << bit): val |= (1 << i)
    if signed and val & (1 << (length - 1)): val -= (1 << length)
    return val

segs = sorted(glob.glob("/data/media/0/realdata/0000004f--*/rlog.zst"))
print(f"ESP_Laengsbeschl@257: {ESPL[:3] if ESPL else None}")
print("方法：实际jerk = [a(t+5) - a(t-5)]/0.1s（0.1s差分窗口，滤掉量化噪声）")
print("规划jerk = longitudinalPlan.jerks（MPC输出）")

tot = {"frames": 0, "plan_jk_gt2": 0, "real_jk_gt2": 0, "real_jk_gt3": 0}
ev = []
for si in range(15):
    lr = LogReader(segs[si])
    st = {"f": 0, "en": False, "espl": [], "plan_jk": 0.0, "real_jk": 0.0,
          "v": 0.0, "mom": 0, "verz": 0.0}
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            st["en"] = msg.carState.cruiseState.enabled
            st["v"] = msg.carState.vEgo
        elif msg.which() == "longitudinalPlan" and st["en"]:
            j = msg.longitudinalPlan.jerks
            st["plan_jk"] = max(abs(x) for x in j) if j else 0.0
        elif msg.which() == "can":
            for c in msg.can:
                if c.address == 257 and len(c.dat) >= 6:
                    d = bytes(c.dat)
                    a = get_sig(d, ESPL[0], ESPL[1], ESPL[2]) * ESPL[3] + ESPL[4]
                    st["espl"].append((f, a))
                    if len(st["espl"]) > 400: st["espl"].pop(0)
        # 实际jerk：每帧用前后5帧(±0.05s)的espl差分
        if len(st["espl"]) >= 11 and st["en"]:
            cur = st["espl"][-1]
            # 找 t-5 帧
            past = [x for x in st["espl"] if x[0] <= f - 5]
            if past:
                a0 = past[-1][1]
                dt = (cur[0] - past[-1][0]) / 100.0
                if dt > 0.05:
                    st["real_jk"] = (cur[1] - a0) / dt
            tot["frames"] += 1
            if abs(st["plan_jk"]) > 2.0: tot["plan_jk_gt2"] += 1
            if abs(st["real_jk"]) > 2.0: tot["real_jk_gt2"] += 1
            if abs(st["real_jk"]) > 3.0:
                tot["real_jk_gt3"] += 1
                if len(ev) < 12:
                    ev.append((si, f, st["v"]*3.6, st["plan_jk"], st["real_jk"], st["mom"], st["verz"]))
        st["f"] += 1
    del lr

print(f"\n激活帧: {tot['frames']}")
print(f"规划jerk>2.0 帧: {tot['plan_jk_gt2']} ({100*tot['plan_jk_gt2']/tot['frames']:.2f}%)  ← MPC规划侧")
print(f"实际jerk>2.0 帧: {tot['real_jk_gt2']} ({100*tot['real_jk_gt2']/tot['frames']:.2f}%)  ← 车体ESP实测")
print(f"实际jerk>3.0 帧: {tot['real_jk_gt3']} ({100*tot['real_jk_gt3']/tot['frames']:.2f}%)  ← 明显顿挫")
print(f"\n实际jerk>3 事件（前12个）: 段/帧/vkmh/规划jk/实际jk/mom/verz")
for e in ev:
    print(f"  段{e[0]} 帧{e[1]:>6} v={e[2]:>3.0f} | 规划jk={e[3]:>5.2f} 实际jk={e[4]:>+6.2f} | mom={e[5]:>4.0f} verz={e[6]:>5.2f}")
print("\n判断：实际jerk明显>规划jerk → 执行断层（力矩映射/刹车响应）；两者都小 → 体感来自幅度而非jerk")
