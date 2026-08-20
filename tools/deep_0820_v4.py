#!/usr/bin/env python3
"""深挖 v4：段1 停车129秒后按SET无效窗口（帧12800-14200）
+ 段7开头 stO/stS（mismatch窗口）
+ dbc 原厂"起步确认"信号扫描（gas/Anf/Start）"""
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

LS = {n: sig_def(n, 267) for n in ["LS_Tip_Setzen", "LS_Tip_Wiederaufnahme"]}
A = {n: sig_def(n, 269) for n in ["ACC_Momentenanforderung", "ACC_Verz_anf", "ACC_Anhalten", "ACC_Status_ACC"]}

def get_sig(dat, start, length, signed):
    if len(dat) <= (start + length - 1) // 8:
        return 0
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

# ========== ① 段1 帧12800-14200：按SET窗口 ==========
print("="*70)
print("① 段1 帧12800-14200（停车129s后按SET，v=0）")
print("="*70)
lr = LogReader(segs[1])
st = {"v": 0, "f": 0, "stS": -1, "anhS": -1, "momS": -99, "stO": -1, "anhO": -1, "verzO": 99, "set_src0": 0, "set_tx": 0, "last_set_tx": 0}
for msg in lr:
    f = st["f"]
    if msg.which() == "carState":
        st["v"] = msg.carState.vEgo
    elif msg.which() == "can":
        for c in msg.can:
            if c.address == 267 and len(c.dat) >= 4:
                d = bytes(c.dat)
                stz = get_sig(d, LS["LS_Tip_Setzen"][0], LS["LS_Tip_Setzen"][1], LS["LS_Tip_Setzen"][2])
                if stz and c.src == 0:
                    st["set_src0"] += 1
                if stz and c.src in (1, 130, 128):
                    st["set_tx"] += 1
                    st["last_set_tx"] = f
            elif c.address == 269 and c.src == 2:
                d = bytes(c.dat)
                st["stS"] = get_sig(d, A["ACC_Status_ACC"][0], A["ACC_Status_ACC"][1], A["ACC_Status_ACC"][2])
                st["anhS"] = get_sig(d, A["ACC_Anhalten"][0], A["ACC_Anhalten"][1], A["ACC_Anhalten"][2])
                st["momS"] = get_sig(d, A["ACC_Momentenanforderung"][0], A["ACC_Momentenanforderung"][1], A["ACC_Momentenanforderung"][2])
            elif c.address == 269 and c.src == 128:
                d = bytes(c.dat)
                st["stO"] = get_sig(d, A["ACC_Status_ACC"][0], A["ACC_Status_ACC"][1], A["ACC_Status_ACC"][2])
                st["anhO"] = get_sig(d, A["ACC_Anhalten"][0], A["ACC_Anhalten"][1], A["ACC_Anhalten"][2])
                st["verzO"] = get_sig(d, A["ACC_Verz_anf"][0], A["ACC_Verz_anf"][1], A["ACC_Verz_anf"][2]) * 0.005 - 7.22
    if 12800 <= f <= 14200 and f % 30 == 0:
        print(f"帧{f:>6}: v={st['v']*3.6:>3.0f} 用户SET帧(已{st['set_src0']:>3}) OP转发SET帧(已{st['set_tx']:>3}) | "
              f"原厂 stS={st['stS']:>2} anhS={st['anhS']} momS={st['momS']:>4.0f} | "
              f"OP stO={st['stO']:>2} anhO={st['anhO']} verzO={st['verzO']:>5.2f}")
    st["f"] += 1
    if f > 14200:
        break
del lr
print(f"\n窗口统计: 用户SET帧(原厂src=0)={st['set_src0']}次 | OP转发SET帧(src 1/130/128)={st['set_tx']}次(最后@帧{st['last_set_tx']})")

# ========== ② 段7 开头：stO/stS/en（mismatch窗口）==========
print("\n" + "="*70)
print("② 段7 开头 4000 帧：OP代发 stO vs 原厂 stS vs en（mismatch 窗口）")
print("="*70)
lr = LogReader(segs[7])
st = {"f": 0, "en": 0, "stS": -1, "stO": -1}
for msg in lr:
    if msg.which() == "carState":
        st["en"] = msg.carState.cruiseState.enabled
    elif msg.which() == "can":
        for c in msg.can:
            if c.address == 269 and c.src == 2:
                d = bytes(c.dat)
                st["stS"] = get_sig(d, A["ACC_Status_ACC"][0], A["ACC_Status_ACC"][1], A["ACC_Status_ACC"][2])
            elif c.address == 269 and c.src == 128:
                d = bytes(c.dat)
                st["stO"] = get_sig(d, A["ACC_Status_ACC"][0], A["ACC_Status_ACC"][1], A["ACC_Status_ACC"][2])
    f = st["f"]
    if f % 250 == 0 and f <= 4000:
        print(f"帧{f:>5}: en={st['en']} OP代发stO={st['stO']:>2} 原厂stS={st['stS']:>2} 匹配={'是' if st['stO']==st['stS'] else '**否**'}")
    st["f"] += 1
    if f > 4000:
        break
del lr

# ========== ③ dbc 原厂"起步确认"信号扫描 ==========
print("\n" + "="*70)
print("③ ACC 报文中 gas/Anf/Start/确认 相关信号（原厂起步确认机制）")
print("="*70)
pat = re.compile(r'SG_ (\w*[Gg]as\w*|\w*[Aa]nf[a-z]*\w*|\w*[Ss]tart\w*|\w*[Bb]estaet\w*|\w*[Ww]ieder\w*) :', dbc_text)
seen = set()
for m in pat.finditer(dbc_text):
    name = m.group(1)
    if name not in seen:
        seen.add(name)
        print(f"  {name}")
if not seen:
    print("  （无匹配信号）")
