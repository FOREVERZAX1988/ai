#!/usr/bin/env python3
"""_probe_resume_pulses.py <rlog.zst> [lo] [hi]

扫 LS_01(0x10B, addr 267) 的 LS_Tip_Wiederaufnahme(19|1@1+) 上升/下降沿。
src 0/128 = OP 代发的按键帧（写 bus0/bus1 收条）；src 130 = OP 写 bus2(CAN.ext) 的收条
-> SnGCarController 代发 RESUME 实际是"OP 在 bus2 上模拟人按 RESUME"。
用于判定"停车后再次起步"的发起者。
"""
import sys
sys.path.insert(0, '/data/openpilot')
from openpilot.tools.lib.logreader import LogReader

path = sys.argv[1]
lo = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
hi = float(sys.argv[3]) if len(sys.argv) > 3 else 1e18

last, edges = {}, []
for e in LogReader(path):
    t = e.logMonoTime / 1e9
    if t < lo or t > hi or e.which() != 'can':
        continue
    for m in e.can:
        if m.address != 267:
            continue
        tip = (bytes(m.dat)[2] >> 3) & 1           # LS_Tip_Wiederaufnahme : 19|1@1+
        if last.get(m.src) != tip:
            last[m.src] = tip
            edges.append((t, m.src, tip))

print("=== LS_01(267) LS_Tip_Wiederaufnahme 边沿 ===")
for t, src, v in edges:
    if v == 1:
        bus = src - 128 if src >= 128 else src
        print("%8.2f src=%3d (bus%d) tip=1  <<< RESUME 按下" % (t, src, bus))
    elif src >= 128:
        print("%8.2f src=%3d (bus%d) tip=0  抬起" % (t, src, src - 128))
