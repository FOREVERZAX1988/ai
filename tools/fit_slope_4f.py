#!/usr/bin/env python3
"""坡度补偿拟合：重建今早 4f 的补偿链并验证生效性
slope_oem = (esp_laengsbeschl - aEgo)/9.81*100（carcontroller 公式）
补偿 accel = 9.81*sin(atan(slope_used/100))；预期 mom 修正 = 补偿*85 Nm/(m/s²)
关键判定：espl 跳变时 mom 是否同步跳（生效）还是不跳（未生效）"""
import glob, sys, re, math
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

DBC = "opendbc_repo/opendbc/dbc/vw_mlb.dbc"
dbc_text = open(DBC, encoding="latin-1").read()
def sig_def(name, msg_id):
    m = re.search(rf'^ SG_ {name} : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)', dbc_text, re.M)
    if not m: return None
    return (int(m.group(1)), int(m.group(2)), m.group(4)=='-', float(m.group(5)), float(m.group(6)))
ESPL = sig_def("ESP_Laengsbeschl", 257)
A = {n: sig_def(n, 269) for n in ["ACC_Verz_anf", "ACC_Momentenanforderung"]}
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
lr = LogReader(segs[8])
st = {"f": 0, "v": 0.0, "aEgo": 0.0, "en": False,
      "espl": 0.0, "verzO": 99, "momO": -99, "filt": 0.0, "has_field": False}
print("=== 段8 坡度补偿重建（前 6000 帧，步长20）===")
print(f"{'帧':>6} {'v':>5} {'aEgo':>6} | {'espl':>6} {'slope%':>6} {'filt%':>6} | {'verzO':>6} {'momO':>5}")
for msg in lr:
    f = st["f"]
    if msg.which() == "carState":
        cs = msg.carState
        st["v"] = cs.vEgo
        st["aEgo"] = cs.aEgo
        st["en"] = cs.cruiseState.enabled
        if not st["has_field"]:
            st["has_field"] = hasattr(cs, 'esp_laengsbeschl')
            if st["has_field"]:
                print("[rlog carState 含 esp_laengsbeschl 字段: True —— 可直接重建]")
    elif msg.which() == "can":
        for c in msg.can:
            if c.address == 257 and len(c.dat) >= 6:
                d = bytes(c.dat)
                st["espl"] = get_sig(d, ESPL[0], ESPL[1], ESPL[2]) * ESPL[3] + ESPL[4]
            elif c.address == 269 and c.src == 128 and len(c.dat) >= 8:
                d = bytes(c.dat)
                st["verzO"] = get_sig(d, A["ACC_Verz_anf"][0], A["ACC_Verz_anf"][1], A["ACC_Verz_anf"][2]) * 0.005 - 7.22
                st["momO"] = get_sig(d, A["ACC_Momentenanforderung"][0], A["ACC_Momentenanforderung"][1], A["ACC_Momentenanforderung"][2])
    if st["en"] and st["v"] > 1.0:
        slope_oem = (st["espl"] - st["aEgo"]) / 9.81 * 100.0
        st["filt"] = 0.8 * st["filt"] + 0.2 * slope_oem
        if f % 20 == 0 and f <= 6000:
            print(f"{f:>6} {st['v']*3.6:>5.0f} {st['aEgo']:>6.2f} | {st['espl']:>6.3f} {slope_oem:>6.2f} {st['filt']:>6.2f} | {st['verzO']:>6.2f} {st['momO']:>5.0f}")
    st["f"] += 1
    if f > 6000: break
del lr
