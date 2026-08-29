#!/usr/bin/env python3
"""精确对齐: OP st=6 触发帧前后, ACC_19.st / Motor_51 TSK_Status / carState.accFaulted"""
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

# ACC_19 帧ID: 查dbc
import re
lines = open("/data/openpilot/opendbc_repo/opendbc/dbc/vw_mlb.dbc").read().splitlines()
acc19_id = None; tsk06_id = None; acc19_st_bit = None
for i,l in enumerate(lines):
    if l.startswith("BO_ ") and "ACC_19" in l:
        acc19_id = int(l.split()[1]); print("ACC_19 ID =", acc19_id, "(0x%X)" % acc19_id)
    if l.startswith("BO_ ") and ("TSK_06" in l or "Motor_51" in l):
        tsk06_id = int(l.split()[1]); print("TSK_06/Motor_51 ID =", tsk06_id, "(0x%X)" % tsk06_id)
# ACC_19 的 ACC_Status_ACC 位: 60|3 (第47行)
acc19_st_bit = 60

sp = glob.glob(f"{BASE}/00000065--*--5/rlog.zst")[0]
seq = 0
st1_prev = None
acc19_st = None; tsk = None; carf = None; canv = None; vego = None
events = []
for m in LogReader(sp):
    w = m.which()
    if w == 'can':
        for c in m.can:
            if c.address == acc19_id and c.src == 2 and len(c.dat) >= 8:
                acc19_st = extract(c.dat, acc19_st_bit, 3)
            if c.address == tsk06_id and c.src == 0 and len(c.dat) >= 8:
                tsk = extract(c.dat, 16, 2)
            if c.address == 269:
                st = extract(c.dat, 57, 3)
                if c.src == 128:
                    if st == 6 and st1_prev != 6:
                        events.append((seq, acc19_st, tsk, carf, canv, vego, st))
                    st1_prev = st
    elif w == 'carState':
        cs = m.carState
        carf = bool(getattr(cs, 'accFaulted', None))
        canv = bool(getattr(cs, 'canValid', None))
        vego = None if cs.vEgo is None else round(cs.vEgo*3.6, 1)
    seq += 1
print(f"\n=== OP st=6 触发事件 (共{len(events)}次) ===")
print(f"{'seq':>7} {'ACC19st':>6} {'TSK':>4} {'accFaulted':>10} {'canValid':>8} {'vEgo':>6} {'OPst':>4}")
for e in events[:15]:
    print(f"{e[0]:>7} {str(e[1]):>6} {str(e[2]):>4} {str(e[3]):>10} {str(e[4]):>8} {str(e[5]):>6} {e[6]:>4}")
