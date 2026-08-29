#!/usr/bin/env python3
"""seg5: OP st=6 触发点附近的 carState(accFaulted/canValid/gas/vego) + checksum校验"""
import sys, glob, os
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
BASE = "/data/media/0/realdata"

def extract(dat, start, length):
    val = 0
    for i in range(length):
        pos = start - i
        b = pos // 8; bit = pos % 8
        v = (dat[b] >> (7 - bit)) & 1 if b < len(dat) else 0
        val = (val << 1) | v
    return val

sp = glob.glob("/data/media/0/realdata/00000065--*--5/rlog.zst")[0]
seq = 0
st1 = st2 = None
fault_events = []
cs_rows = []
for m in LogReader(sp):
    w = m.which()
    if w == 'can':
        for c in m.can:
            if c.address == 269:
                st = extract(c.dat, 57, 3)
                if c.src == 128:
                    if st1 is None or (st == 6 and st1 != 6):
                        fault_events.append((seq, st, st2))
                    st1 = st
                elif c.src == 2:
                    st2 = st
    elif w == 'carState':
        cs = m.carState
        cs_rows.append((seq, getattr(cs, 'accFaulted', None), getattr(cs, 'canValid', None),
                        getattr(cs, 'gasPressed', None), getattr(cs, 'vEgo', None)))
    seq += 1
print("=== OP st=6 进入事件 (seq, OP_st, 原厂st) ===")
for e in fault_events[:15]:
    print(f"  seq{e[0]}: OP→st={e[1]} 原厂st={e[2]}")
print("\n=== carState accFaulted/canValid 时间线 (每20条) ===")
for r in cs_rows[::20]:
    print(f"  seq{r[0]}: accFaulted={r[1]} canValid={r[2]} gas={r[3]} vEgo={None if r[4] is None else round(r[4]*3.6,1)}km/h")
