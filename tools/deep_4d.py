#!/usr/bin/env python3
"""对比验证：0000004d（0816分支，8-18路试）停车事件——anhO 状态 + 按键 + 原厂响应
目标：检验"anh=1 锁死"（4d记忆结论）vs "anh=0 原厂锁"（4f实测）哪个对
扁平文件格式：0000004d--ee05d205c3--N--rlog.zst"""
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

A = {n: sig_def(n, 269) for n in ["ACC_Momentenanforderung", "ACC_Verz_anf", "ACC_Anhalten", "ACC_Status_ACC"]}
LS = {n: sig_def(n, 267) for n in ["LS_Tip_Setzen", "LS_Tip_Wiederaufnahme"]}
print("defs OK:", {k: v[:2] for k, v in A.items()}, {k: v[:2] for k, v in LS.items()})

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

segs = sorted(glob.glob("/data/media/0/realdata/0000004d--*--rlog.zst"))
print(f"4d 段数: {len(segs)}")

def seg_no(p):
    m = re.search(r'--(\d+)--rlog', p)
    return int(m.group(1)) if m else -1

print("\n=== 停车事件（enabled 且 v<0.1 持续≥5秒）===")
print(f"{'段':>3} {'起始帧':>7} {'时长s':>5} {'anhO=1帧':>8} {'anhO=0帧':>8} {'按键':>4} {'车动?':>5}")
events_total = 0
for p in segs:
    si = seg_no(p)
    try:
        lr = LogReader(p)
    except Exception as e:
        print(f"段{si}: 读取失败 {e}")
        continue
    st = {"v": 0.0, "en": False, "f": 0, "anhO": 0, "stS": -1}
    stop_start = None
    stop_anh1 = 0
    stop_anh0 = 0
    stop_keys = 0
    car_moved = False
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            cs = msg.carState
            st["v"] = cs.vEgo
            st["en"] = cs.cruiseState.enabled
        elif msg.which() == "can":
            for c in msg.can:
                if c.address == 269:
                    d = bytes(c.dat)
                    if c.src == 128:  # OP 代发（4d 时代 src=128? 待确认，先按 128）
                        st["anhO"] = get_sig(d, A["ACC_Anhalten"][0], A["ACC_Anhalten"][1], A["ACC_Anhalten"][2])
                    elif c.src == 2:
                        st["stS"] = get_sig(d, A["ACC_Status_ACC"][0], A["ACC_Status_ACC"][1], A["ACC_Status_ACC"][2])
                elif c.address == 267 and c.src == 0 and len(c.dat) >= 4:
                    d = bytes(c.dat)
                    stz = get_sig(d, LS["LS_Tip_Setzen"][0], LS["LS_Tip_Setzen"][1], LS["LS_Tip_Setzen"][2])
                    rsm = get_sig(d, LS["LS_Tip_Wiederaufnahme"][0], LS["LS_Tip_Wiederaufnahme"][1], LS["LS_Tip_Wiederaufnahme"][2])
                    if stz or rsm:
                        stop_keys += 1
        if st["en"] and st["v"] < 0.1:
            if stop_start is None:
                stop_start = f
            if st["anhO"] == 1:
                stop_anh1 += 1
            else:
                stop_anh0 += 1
        else:
            if stop_start is not None:
                dur = f - stop_start
                if dur >= 500:  # ≥5秒
                    car_moved = st["v"] > 0.5
                    events_total += 1
                    print(f"{si:>3} {stop_start:>7} {dur/100:>5.0f} {stop_anh1:>8} {stop_anh0:>8} {stop_keys:>4} {car_moved!s:>5}")
                    if events_total >= 25:
                        del lr
                        print(f"... 已显示{events_total}个事件（总计扫描中）")
                        raise SystemExit
                stop_start = None
                stop_anh1 = 0
                stop_anh0 = 0
                stop_keys = 0
        st["f"] += 1
    del lr
print(f"共 {events_total} 个停车事件（≥5s）")
