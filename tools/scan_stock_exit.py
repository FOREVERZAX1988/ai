#!/usr/bin/env python3
"""用"原厂stS"判定巡航退出：gas=1 时段内（或松开后3s），原厂 src=2 的 ACC_Status_ACC
从 4(超驰)/3(激活) 变 0(off)/6(故障) → 原厂退出（仪表盘灰，OP enabled 可能延迟未变）
扫描：0000004e（今早预热）+ 0000004f 段0-6（第一段）"""
import glob, sys, re
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

DBC = "opendbc_repo/opendbc/dbc/vw_mlb.dbc"
dbc_text = open(DBC, encoding="latin-1").read()
def sig_def(name, msg_id):
    m = re.search(rf'^ SG_ {name} : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)', dbc_text, re.M)
    if not m: return None
    return (int(m.group(1)), int(m.group(2)), m.group(4)=='-', float(m.group(5)), float(m.group(6)))
ST = sig_def("ACC_Status_ACC", 269)
def get_sig(dat, start, length, signed):
    if len(dat) <= (start + length - 1) // 8: return 0
    val = 0
    for i in range(length):
        byte = (start + i) // 8
        bit = (start + i) % 8
        if dat[byte] & (1 << bit): val |= (1 << i)
    if signed and val & (1 << (length - 1)): val -= (1 << length)
    return val

def scan(segs, label, seg_range):
    print(f"\n===== {label} =====")
    print(f"{'段':>2} {'踩油门起':>7} {'退出帧':>7} {'时长s':>6} {'stS变化':>8} {'en变化':>8}")
    tot = exit_n = 0
    for si in seg_range:
        lr = LogReader(segs[si])
        st = {"f": 0, "gas": 0, "en": 0, "stS": -1, "pstS": -1, "pg": 0, "pe": 0, "v": 0.0}
        gas_start = None
        in_gas = False
        for msg in lr:
            f = st["f"]
            if msg.which() == "carState":
                cs = msg.carState
                st["gas"] = cs.gasPressed
                st["en"] = cs.cruiseState.enabled
                st["v"] = cs.vEgo
            elif msg.which() == "can":
                for c in msg.can:
                    if c.address == 269 and c.src == 2 and len(c.dat) >= 8:
                        d = bytes(c.dat)
                        st["stS"] = get_sig(d, ST[0], ST[1], ST[2])
            if st["gas"] and not in_gas:
                gas_start = f
                in_gas = True
            # 原厂退出检测：stS 从 3/4 变 0/6
            if in_gas and st["pstS"] in (3, 4) and st["stS"] in (0, 6) and f > gas_start + 5:
                tot += 1; exit_n += 1
                en_str = "en退出" if (st["pe"] and not st["en"]) else "en保持"
                print(f"{si:>2} {gas_start:>7} {f:>7} {(f-gas_start)/100:>6.2f} {st['pstS']:>4}→{st['stS']:<3} {en_str:>8}")
                in_gas = False
                gas_start = None
            if in_gas and st["pg"] == 1 and st["gas"] == 0:
                tot += 1
                in_gas = False
                gas_start = None
            st["pg"] = st["gas"]; st["pe"] = st["en"]; st["pstS"] = st["stS"]
            st["f"] += 1
        del lr
    print(f"踩油门时段: {tot} | 原厂退出: {exit_n}")

# 4e（目录格式）
segs_4e = sorted(glob.glob("/data/media/0/realdata/0000004e--*/rlog.zst"))
scan(segs_4e, "0000004e（今早预热 19段）", range(min(19, len(segs_4e))))
# 4f 段0-6
segs_4f = sorted(glob.glob("/data/media/0/realdata/0000004f--*/rlog.zst"))
scan(segs_4f, "0000004f 段0-6（第一段全关）", range(0, 7))
