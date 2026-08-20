#!/usr/bin/env python3
"""验证 stO 位解析：读 4e 段2 34390 帧 src=128 的 269 原始 dat，
用两种位定义（60|3 和 57|3）交叉解析 ACC_Status_ACC + ACC_Momentenanforderung"""
import glob, sys, re
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

segs = sorted(glob.glob("/data/media/0/realdata/0000004e--*/rlog.zst"))
lr = LogReader(segs[2])
st = {"f": 0}
found = None
for msg in lr:
    f = st["f"]
    if msg.which() == "can":
        for c in msg.can:
            if c.address == 269 and c.src == 128 and len(c.dat) >= 8 and 34385 <= f <= 34395:
                d = bytes(c.dat)
                # 位解析 60|3
                v60 = ((d[7] >> 4) & 0x7)
                # 位解析 57|3
                v57 = ((d[7] >> 1) & 0x7)
                # mom 16|10
                mom = d[2] | ((d[3] & 0x03) << 8)
                # verz 32|11 (有符号)
                raw_vz = d[4] | ((d[5] & 0x07) << 8)
                if raw_vz & 0x400: raw_vz -= 0x800
                verz = raw_vz * 0.005 - 7.22
                print(f"帧{f} src=128 ACC_05 dat={d.hex()}")
                print(f"  ACC_Status_ACC: 60|3读出={v60} | 57|3读出={v57}")
                print(f"  mom(16|10)={mom} verz(32|11)={verz:.2f}")
                print(f"  byte7={d[7]:#04x} (bit4-6=60|3, bit1-3=57|3)")
                found = f
                break
    st["f"] += 1
    if found: break
del lr
if not found:
    print("未找到帧")
