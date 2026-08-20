#!/usr/bin/env python3
"""4f 未完成项深挖：
① 段7 开头 TSK_Status（原厂 ACC 状态机）——查 mismatch 的瞬时跳变
② 段9 踩油门松开后 OP 代发恢复（stO/verzO/momO）
③ 段12 gasPressed 连续性（确认是否持续踩而非多次踩松）"""
import glob, sys, re
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
from collections import Counter

DBC = "opendbc_repo/opendbc/dbc/vw_mlb.dbc"
dbc_text = open(DBC, encoding="latin-1").read()
def sig_def(name, msg_id):
    m = re.search(rf'^ SG_ {name} : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)', dbc_text, re.M)
    if not m: return None
    return (int(m.group(1)), int(m.group(2)), m.group(4)=='-', float(m.group(5)), float(m.group(6)))
TSK = sig_def("TSK_Status", 268)
A = {n: sig_def(n, 269) for n in ["ACC_Verz_anf", "ACC_Momentenanforderung", "ACC_Status_ACC"]}
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

# ========== ① 段7 开头 TSK_Status ==========
print("="*60)
print("① 段7 开头 8000 帧：TSK_Status(268) 跳变 + src 分布")
print("="*60)
lr = LogReader(segs[7])
srcs = Counter()
st = {"f": 0, "tsk": -1, "last_tsk": -1, "en": 0}
jumps = []
for msg in lr:
    f = st["f"]
    if msg.which() == "carState":
        st["en"] = msg.carState.cruiseState.enabled
    elif msg.which() == "can":
        for c in msg.can:
            if c.address == 268 and len(c.dat) >= 8:
                srcs[c.src] += 1
                d = bytes(c.dat)
                st["tsk"] = get_sig(d, TSK[0], TSK[1], TSK[2])
                if st["last_tsk"] != -1 and st["tsk"] != st["last_tsk"]:
                    jumps.append((f, st["last_tsk"], st["tsk"]))
                st["last_tsk"] = st["tsk"]
    if f % 2000 == 0 and f <= 8000:
        print(f"帧{f}: en={st['en']} TSK_Status={st['tsk']}")
    st["f"] += 1
    if f > 8000: break
del lr
print(f"268 src 分布: {dict(srcs)}")
print(f"TSK_Status 跳变: {jumps[:12] if jumps else '无'}")

# ========== ② 段9 松开油门后 OP 代发恢复 ==========
print("\n" + "="*60)
print("② 段9 踩油门→松开：OP 代发 stO/verzO/momO 恢复情况")
print("="*60)
lr = LogReader(segs[9])
st = {"f": 0, "gas": 0, "en": 0, "v": 0.0,
      "verzO": 99, "momO": -99, "stO": -1, "pg": 0}
release_frames = []
for msg in lr:
    f = st["f"]
    if msg.which() == "carState":
        cs = msg.carState
        st["gas"] = cs.gasPressed; st["en"] = cs.cruiseState.enabled; st["v"] = cs.vEgo
    elif msg.which() == "can":
        for c in msg.can:
            if c.address == 269 and c.src == 128 and len(c.dat) >= 8:
                d = bytes(c.dat)
                st["verzO"] = get_sig(d, A["ACC_Verz_anf"][0], A["ACC_Verz_anf"][1], A["ACC_Verz_anf"][2]) * 0.005 - 7.22
                st["momO"] = get_sig(d, A["ACC_Momentenanforderung"][0], A["ACC_Momentenanforderung"][1], A["ACC_Momentenanforderung"][2])
                st["stO"] = get_sig(d, A["ACC_Status_ACC"][0], A["ACC_Status_ACC"][1], A["ACC_Status_ACC"][2])
    if st["pg"] == 1 and st["gas"] == 0 and st["en"]:
        release_frames.append(f)
    st["pg"] = st["gas"]
    st["f"] += 1
    if f > 60000: break
del lr
print(f"松开油门事件: {release_frames}")
if release_frames:
    rf = release_frames[0]
    # 松开前 1 秒到松开后 2 秒
    lr = LogReader(segs[9])
    st = {"f": 0, "gas": 0, "en": 0, "verzO": 99, "momO": -99, "stO": -1, "v": 0.0}
    print(f"{'帧':>7} {'gas':>3} {'en':>3} {'v':>4} | {'verzO':>6} {'momO':>5} {'stO':>3}")
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            cs = msg.carState
            st["gas"] = cs.gasPressed; st["en"] = cs.cruiseState.enabled; st["v"] = cs.vEgo
        elif msg.which() == "can":
            for c in msg.can:
                if c.address == 269 and c.src == 128 and len(c.dat) >= 8:
                    d = bytes(c.dat)
                    st["verzO"] = get_sig(d, A["ACC_Verz_anf"][0], A["ACC_Verz_anf"][1], A["ACC_Verz_anf"][2]) * 0.005 - 7.22
                    st["momO"] = get_sig(d, A["ACC_Momentenanforderung"][0], A["ACC_Momentenanforderung"][1], A["ACC_Momentenanforderung"][2])
                    st["stO"] = get_sig(d, A["ACC_Status_ACC"][0], A["ACC_Status_ACC"][1], A["ACC_Status_ACC"][2])
        if rf - 100 <= f <= rf + 200 and f % 25 == 0:
            print(f"{f:>7} {int(st['gas']):>3} {int(st['en']):>3} {st['v']*3.6:>4.0f} | {st['verzO']:>6.2f} {st['momO']:>5.0f} {st['stO']:>3}")
        st["f"] += 1
    del lr

# ========== ③ 段12 gasPressed 连续性 ==========
print("\n" + "="*60)
print("③ 段12 gasPressed 帧分布（连续 vs 多次踩松）")
print("="*60)
lr = LogReader(segs[12])
st = {"f": 0, "gas": 0, "pg": 0, "gas_on": [], "cur_start": None}
for msg in lr:
    f = st["f"]
    if msg.which() == "carState":
        st["gas"] = msg.carState.gasPressed
    if st["gas"] and st["cur_start"] is None:
        st["cur_start"] = f
    elif not st["gas"] and st["cur_start"] is not None:
        st["gas_on"].append((st["cur_start"], f))
        st["cur_start"] = None
    st["f"] += 1
    if f > 60000: break
del lr
if st["cur_start"] is not None:
    st["gas_on"].append((st["cur_start"], 60000))
print(f"gasPressed 持续段: {[(s, e, f'{(e-s)/100:.1f}s') for s, e in st['gas_on']]}")
