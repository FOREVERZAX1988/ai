#!/usr/bin/env python3
"""dump_bus269.py — dump 段内各 bus 的 269 帧原始字节（确认 OP 代发总线）
用法: python3 dump_bus269.py ROUTE SEG [起始269帧号] [帧数]
"""
import sys, glob
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

ROUTE, SEG = sys.argv[1], sys.argv[2]
START = int(sys.argv[3]) if len(sys.argv) > 3 else 0
N = int(sys.argv[4]) if len(sys.argv) > 4 else 25
BASE = "/data/media/0/realdata"
p = glob.glob(f"{BASE}/{ROUTE}--*--{SEG}/rlog.zst")
if not p: print("无段"); sys.exit(1)

def extract(dat, start, length):
    val = 0
    for i in range(length):
        pos = start - i
        b = pos // 8; bit = pos % 8
        v = (dat[b] >> (7 - bit)) & 1 if b < len(dat) else 0
        val = (val << 1) | v
    return val

cnt = 0
for m in LogReader(p[0]):
    if m.which() != 'can': continue
    for c in m.can:
        if c.address != 269: continue
        cnt += 1
        if cnt < START: continue
        if cnt > START + N: break
        d = bytes(c.dat)
        st = extract(d,57,3); verz = extract(d,32,11); axg = extract(d,48,9)
        mom = extract(d,16,10); loes = extract(d,43,1); fv = extract(d,13,1); fm = extract(d,12,1)
        print(f"#{cnt} bus{c.src} raw={d.hex()} st={st} verz_raw={verz}({verz*0.005-7.22:.2f}) "
              f"axg_raw={axg}({axg*0.024-2.016:.2f}) mom={mom} loes={loes} FV={fv} FM={fm}")
