#!/usr/bin/env python3
"""深挖 v2（真实数据）：0000004f
① 停车后按SET/RESUME：用户按键(src=2 267) → OP转发(src=128 267) → 原厂响应(stS/anhS/momS) → 车动
② controlsMismatch：段7开头(第二段点火/切开关) alertText + TSK_Status
③ 踩油门介入松开后纵向退出：gasPressed 1→0 → cruiseState.enabled"""
import glob, sys, re
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

DBC = "opendbc_repo/opendbc/dbc/vw_mlb.dbc"
dbc_text = open(DBC, encoding="latin-1").read()

def sig_def(name, msg_id):
    m = re.search(rf'^ SG_ {name} : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)', dbc_text, re.M)
    if not m:
        return None
    start, length, signed = int(m.group(1)), int(m.group(2)), m.group(4) == '-'
    scale, offset = float(m.group(5)), float(m.group(6))
    lines = dbc_text.splitlines()
    for i, ln in enumerate(lines):
        if f'SG_ {name} ' in ln:
            for j in range(i, -1, -1):
                bm = re.match(r'^BO_ (\d+) (\w+)', lines[j])
                if bm and int(bm.group(1)) == msg_id:
                    return start, length, signed, scale, offset
    return None

# LS_01(267) 按键信号
LS = {n: sig_def(n, 267) for n in ["LS_Tip_Setzen", "LS_Tip_Wiederaufnahme", "LS_Hauptschalter"]}
# ACC_05(269)
A = {n: sig_def(n, 269) for n in ["ACC_Momentenanforderung", "ACC_Verz_anf", "ACC_Anhalten", "ACC_Status_ACC"]}
print("LS_01 defs:", {k: (v[:2] if v else None) for k, v in LS.items()})
print("ACC_05 defs:", {k: (v[:2] if v else None) for k, v in A.items()})

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

segs = sorted(glob.glob("/data/media/0/realdata/0000004f--*/rlog.zst"))
print(f"段数: {len(segs)}")

# ========== ① 段7 停车窗口：用户按SET → OP转发 → 原厂响应 ==========
print("\n" + "="*60)
print("① 段7：用户按键(Setzen/Wiederaufnahme) → OP转发 → 原厂响应")
print("="*60)
lr = LogReader(segs[7])
st = {"v": 0, "gas": 0, "f": 0, "stS": -1, "anhS": -1, "momS": -99, "verzS": 99, "stO": -1, "anhO": -1}
events = []
last_key_frame = None
for msg in lr:
    f = st["f"]
    if msg.which() == "carState":
        st["v"] = msg.carState.vEgo
        st["gas"] = msg.carState.gasPressed
    elif msg.which() == "can":
        for c in msg.can:
            if c.address == 267 and (c.src in (2, 128)):
                d = bytes(c.dat)
                stz = get_sig(d, LS["LS_Tip_Setzen"][0], LS["LS_Tip_Setzen"][1], LS["LS_Tip_Setzen"][2])
                rsm = get_sig(d, LS["LS_Tip_Wiederaufnahme"][0], LS["LS_Tip_Wiederaufnahme"][1], LS["LS_Tip_Wiederaufnahme"][2])
                if stz or rsm:
                    # 按键时刻：原厂(src=2) 或 OP代发(src=128)
                    key = "原厂" if c.src == 2 else "OP代发"
                    if c.src == 2:
                        last_key_frame = f
                        events.append((f, key, stz, rsm, "按键"))
                    else:
                        events.append((f, key, stz, rsm, "转发"))
            elif c.address == 269 and c.src == 2:
                d = bytes(c.dat)
                st["stS"] = get_sig(d, A["ACC_Status_ACC"][0], A["ACC_Status_ACC"][1], A["ACC_Status_ACC"][2])
                st["anhS"] = get_sig(d, A["ACC_Anhalten"][0], A["ACC_Anhalten"][1], A["ACC_Anhalten"][2])
                st["momS"] = get_sig(d, A["ACC_Momentenanforderung"][0], A["ACC_Momentenanforderung"][1], A["ACC_Momentenanforderung"][2])
                st["verzS"] = get_sig(d, A["ACC_Verz_anf"][0], A["ACC_Verz_anf"][1], A["ACC_Verz_anf"][2]) * 0.005 - 7.22
            elif c.address == 269 and c.src == 128:
                d = bytes(c.dat)
                st["stO"] = get_sig(d, A["ACC_Status_ACC"][0], A["ACC_Status_ACC"][1], A["ACC_Status_ACC"][2])
                st["anhO"] = get_sig(d, A["ACC_Anhalten"][0], A["ACC_Anhalten"][1], A["ACC_Anhalten"][2])
    # 按键后 3 秒内采样响应
    if last_key_frame is not None and f - last_key_frame in (5, 30, 60, 150, 300) and f % 100 == 0:
        events.append((f, "响应", st["stS"], st["anhS"], f"stS={st['stS']} anhS={st['anhS']} momS={st['momS']} v={st['v']*3.6:.0f}"))
    st["f"] += 1
    if f > 70000:
        break
del lr
print(f"按键事件数: {len([e for e in events if e[4]=='按键'])}")
for e in events[:25]:
    print(f"  帧{e[0]:>6} [{e[1]}] Setzen={e[2]} Resume={e[3]} ({e[4]})")

# ========== ② controlsMismatch：段7开头（第二段点火）alertText ==========
print("\n" + "="*60)
print("② 段7开头(第二段点火/切开关) 的 alertText/TSK 状态")
print("="*60)
lr = LogReader(segs[7])
alerts = []
tsk_vals = []
n = 0
for msg in lr:
    if msg.which() == "selfdrivedState":
        sd = msg.selfdrivedState
        if sd.alertText1:
            alerts.append((n, str(sd.alertText1)[:50]))
        if sd.alertText2:
            alerts.append((n, str(sd.alertText2)[:50]))
    n += 1
    if n > 30000:
        break
del lr
print(f"alertText 事件({len(alerts)}条):")
for f, t in alerts[:12]:
    print(f"  帧{f}: {t}")

# ========== ③ 踩油门介入松开后纵向退出 ==========
print("\n" + "="*60)
print("③ gasPressed 1→0 后 cruiseState.enabled 是否退出（全段）")
print("="*60)
for si in [8, 12, 13, 14]:
    lr = LogReader(segs[si])
    st = {"gas": 0, "en": 0, "f": 0, "prev_gas": 0, "prev_en": 0}
    exits = []
    for msg in lr:
        if msg.which() == "carState":
            cs = msg.carState
            st["gas"] = cs.gasPressed
            st["en"] = cs.cruiseState.enabled
        f = st["f"]
        # 油门松开（1→0）且之前 enabled
        if st["prev_gas"] == 1 and st["gas"] == 0 and st["prev_en"]:
            # 之后 1 秒内 enabled 是否保持
            exits.append((f, "松开油门", "en保持" if st["en"] else "en退出!"))
        st["prev_gas"] = st["gas"]
        st["prev_en"] = st["en"]
        st["f"] += 1
        if f > 40000:
            break
    del lr
    print(f"段{si}: 松开油门事件 {len(exits)} 次" + (" | ".join(f"帧{f}{t}" for f, _, t in exits[:5]) if exits else ""))
