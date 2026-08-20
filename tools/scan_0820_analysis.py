#!/usr/bin/env python3
"""0000004f (8.20路试) 四专题综合分析
①SnG 起步时间线 ②纵向摇晃检测 ③直角弯 ④横纵冲突
全部从信号实锤出发，不猜。输出到文件+stdout摘要"""
import glob, sys, math, re, os
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

DBC = "opendbc_repo/opendbc/dbc/vw_mlb.dbc"
dbc_text = open(DBC, encoding="latin-1").read()

def sig_def(name, msg_id=None):
    m = re.search(rf'^ SG_ {name} : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)', dbc_text, re.M)
    if not m:
        return None
    start, length, signed = int(m.group(1)), int(m.group(2)), m.group(4) == '-'
    scale, offset = float(m.group(5)), float(m.group(6))
    lines = dbc_text.splitlines()
    for i, ln in enumerate(lines):
        if f'SG_ {name} ' in ln:
            # 找该 SG_ 所属报文；若指定 msg_id 则只匹配该报文块
            for j in range(i, -1, -1):
                bm = re.match(r'^BO_ (\d+) (\w+)', lines[j])
                if bm:
                    bid = int(bm.group(1))
                    if msg_id is None or bid == msg_id:
                        return bid, start, length, signed, scale, offset
                    else:
                        break
    return None

def get_sig(dat, start, length, signed):
    val = 0
    for i in range(length):
        byte = (start + i) // 8
        bit = (start + i) % 8
        if dat[byte] & (1 << bit):
            val |= (1 << i)
    if signed and val & (1 << (length - 1)):
        val -= (1 << length)
    return val

# ACC_05 信号位定义
ACC_DEFS = {
    "ACC_Momentenanforderung": sig_def("ACC_Momentenanforderung", 269),
    "ACC_Verz_anf": sig_def("ACC_Verz_anf", 269),
    "ACC_Anhalten": sig_def("ACC_Anhalten", 269),
    "ACC_Status_ACC": sig_def("ACC_Status_ACC", 269),
}
print("ACC_05 位定义:", {k: (v[0] if v else None) for k, v in ACC_DEFS.items()})

# 收集 0000004f 全部段
segs = sorted(glob.glob("/data/media/0/realdata/0000004f--*/rlog.zst"))
print(f"段数: {len(segs)}")

out = []
def log(s):
    out.append(s)
    print(s)

# ============ ① SnG 起步时间线 ============
log("\n" + "="*70)
log("① SnG 起步时间线（停车→前车起步→OP请求→车动）")
log("="*70)
for si, p in enumerate(segs):
    try:
        lr = LogReader(p)
    except Exception:
        continue
    # 状态：停车窗口跟踪
    st = {"v": 0.0, "enabled": False, "aTarget": 0.0, "lead_d": 0.0, "lead_v": 0.0,
          "anh": 0, "acc_status": 0, "mom": 0.0, "verz": 3.0, "frame": 0, "t": 0.0}
    stop_start = None   # 停车开始(帧)
    lead_moved = None   # 前车起步迹象(帧)
    target_pos = None   # OP 请求正加速度(帧)
    car_moved = None    # 车动(帧)
    for msg in lr:
        f = st["frame"]
        if msg.which() == "carState":
            cs = msg.carState
            st["v"] = cs.vEgo
            st["enabled"] = cs.cruiseState.enabled
        elif msg.which() == "longitudinalPlan":
            st["aTarget"] = msg.longitudinalPlan.aTarget
        elif msg.which() == "modelV2":
            if len(msg.modelV2.leadsV3) > 0:
                st["lead_d"] = msg.modelV2.leadsV3[0].x[0]
                st["lead_v"] = msg.modelV2.leadsV3[0].v[0]
        elif msg.which() == "can":
            for c in msg.can:
                if c.address == 269 and c.src in (0, 2):  # ACC_05 原厂(2)/OP(0)
                    d = bytes(c.dat)
                    for nm, (bid, start, length, signed, scale, offset) in ACC_DEFS.items():
                        if nm == "ACC_Anhalten":
                            st["anh"] = get_sig(d, start, length, signed)
                        elif nm == "ACC_Status_ACC":
                            st["acc_status"] = get_sig(d, start, length, signed)
                        elif nm == "ACC_Momentenanforderung":
                            st["mom"] = get_sig(d, start, length, signed) * scale + offset
                        elif nm == "ACC_Verz_anf":
                            st["verz"] = get_sig(d, start, length, signed) * scale + offset
        st["frame"] += 1
        # 停车窗口检测
        if st["enabled"] and st["v"] < 0.1:
            if stop_start is None:
                stop_start = f
            else:
                # 前车起步迹象：lead_v > 0.3 或 lead_d 明显增长
                if lead_moved is None and st["lead_v"] > 0.3:
                    lead_moved = f
                # OP 请求起步
                if target_pos is None and st["aTarget"] > 0.05:
                    target_pos = f
                # 车动
                if car_moved is None and st["v"] > 0.5:
                    car_moved = f
        else:
            if stop_start is not None:
                # 停车结束，输出事件
                if stop_start is not None and (car_moved is not None or target_pos is not None or lead_moved is not None):
                    dur = f - stop_start
                    log(f"段{si:>2} 停车事件: 时长{dur}帧 | 前车起步@{lead_moved} | OP请求正a@{target_pos} | 车动@{car_moved} | "
                        f"延时(前车→车动)={car_moved-lead_moved if (car_moved and lead_moved) else 'N/A'}帧 | "
                        f"anh={st['anh']} status={st['acc_status']} verz={st['verz']:.2f}")
                stop_start = None
                lead_moved = target_pos = car_moved = None
    del lr

# ============ ② 纵向摇晃检测（第二段 段7-14）============
log("\n" + "="*70)
log("② 纵向摇晃：aEgo 高频跳变统计（段7-14 全开段）")
log("="*70)
for si in range(7, 15):
    if si >= len(segs):
        break
    try:
        lr = LogReader(segs[si])
    except Exception:
        continue
    prev_a = None
    jumps = 0
    neg_pos = 0  # 正负交替次数
    prev_sign = 0
    n = 0
    for msg in lr:
        if msg.which() == "carState":
            a = msg.carState.aEgo
            if prev_a is not None:
                da = abs(a - prev_a)
                if da > 0.5:  # 帧间加速度跳变 >0.5 m/s³（100Hz 帧间）
                    jumps += 1
                sign = 1 if a > 0.05 else (-1 if a < -0.05 else 0)
                if sign != 0 and prev_sign != 0 and sign != prev_sign:
                    neg_pos += 1
                if sign != 0:
                    prev_sign = sign
            prev_a = a
            n += 1
        if n > 20000:
            break
    del lr
    log(f"段{si:>2}: 样本{n}帧 帧间跳变(>0.5)={jumps}次 正负交替={neg_pos}次")

# ============ ③ 直角弯：大转向角事件 ============
log("\n" + "="*70)
log("③ 直角弯/大转向角事件（|steer|>25°，全段）")
log("="*70)
for si, p in enumerate(segs):
    try:
        lr = LogReader(p)
    except Exception:
        continue
    st = {"steer": 0.0, "v": 0.0, "a": 0.0, "mom": 0.0, "frame": 0}
    max_steer = 0.0
    max_frame = 0
    event_note = None
    for msg in lr:
        f = st["frame"]
        if msg.which() == "carState":
            cs = msg.carState
            st["steer"] = abs(cs.steeringAngleDeg)
            st["v"] = cs.vEgo
            st["a"] = cs.aEgo
        elif msg.which() == "can":
            for c in msg.can:
                if c.address == 269 and c.src == 0:
                    d = bytes(c.dat)
                    sd = ACC_DEFS["ACC_Momentenanforderung"]
                    st["mom"] = get_sig(d, sd[1], sd[2], sd[3]) * sd[4] + sd[5]
        if st["steer"] > max_steer:
            max_steer = st["steer"]
            max_frame = f
            if max_steer > 25:
                event_note = f"  [大弯] 段{si} 帧{f}: |steer|={max_steer:.0f}° v={st['v']*3.6:.0f}km/h a={st['a']:.2f} mom={st['mom']:.0f}"
        st["frame"] += 1
    if event_note:
        log(event_note)
    del lr

# ============ ④ 横纵冲突：弯中猛加速 ============
log("\n" + "="*70)
log("④ 横纵冲突：|steer|>15° 且 aTarget>1.0 或 aEgo>1.0")
log("="*70)
for si, p in enumerate(segs):
    try:
        lr = LogReader(p)
    except Exception:
        continue
    st = {"steer": 0.0, "aTarget": 0.0, "a": 0.0, "v": 0.0, "frame": 0}
    for msg in lr:
        if msg.which() == "carState":
            cs = msg.carState
            st["steer"] = abs(cs.steeringAngleDeg)
            st["a"] = cs.aEgo
            st["v"] = cs.vEgo
        elif msg.which() == "longitudinalPlan":
            st["aTarget"] = msg.longitudinalPlan.aTarget
        if st["steer"] > 15 and (st["aTarget"] > 1.0 or st["a"] > 1.0):
            log(f"段{si:>2} 帧{st['frame']}: |steer|={st['steer']:.0f}° aTarget={st['aTarget']:.2f} aEgo={st['a']:.2f} v={st['v']*3.6:.0f}km/h  [弯中加速!]")
            # 只报一次（跳过同窗口）——简化：每500帧内只报一次
            st["last_report"] = getattr(st, "last_report", -999)
            if st["frame"] - getattr(st, "last_report", -999) > 100:
                st["last_report"] = st["frame"]
        st["frame"] += 1
    del lr

with open("/data/openpilot/ai/tools/route_0820_analysis.txt", "w") as f:
    f.write("\n".join(out))
print("\n已保存 route_0820_analysis.txt")
