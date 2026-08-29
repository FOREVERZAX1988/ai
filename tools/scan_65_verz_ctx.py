#!/usr/bin/env python3
"""扫描 route 00000065 中 stock verz<=-1.5 的时刻，输出命中点前后verz序列+st+油门。
纯can解码：ACC_05(269) bus2=原厂/bus128=OP; Motor_01(128) bus0 MO_Mom_Fahrerwunsch
"""
import sys, glob, os
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
from collections import deque

ROUTE = sys.argv[1] if len(sys.argv) > 1 else "00000065"
THRESH = float(sys.argv[2]) if len(sys.argv) > 2 else -1.5
BASE = "/data/media/0/realdata"

def extract(dat, start, length):
    val = 0
    for i in range(length):
        pos = start - i
        b = pos // 8; bit = pos % 8
        v = (dat[b] >> (7 - bit)) & 1 if b < len(dat) else 0
        val = (val << 1) | v
    return val

segs = sorted(glob.glob(f"{BASE}/{ROUTE}--*--*/rlog.zst"))
print(f"扫描 {ROUTE} 共 {len(segs)} 段, 阈值 verz<={THRESH}", flush=True)

hits = 0; seg_min = {}
for sp in segs:
    seg = os.path.basename(os.path.dirname(sp)).split('--')[-1]
    hist2 = deque(maxlen=25)   # (verz, st) 原厂历史
    hist1 = deque(maxlen=25)   # OP历史
    gas = 0.0; mmin = 0.0; printed = 0
    try:
        for m in LogReader(sp):
            if m.which() != 'can': continue
            for c in m.can:
                if c.address == 269:
                    if c.src == 2:
                        st2 = extract(c.dat, 57, 3); verz2 = extract(c.dat, 32, 11)*0.005 - 7.22
                        mom2 = extract(c.dat, 16, 10); loes2 = extract(c.dat, 43, 1)
                        hist2.append((verz2, st2, mom2, loes2))
                        if verz2 < mmin: mmin = verz2
                        if verz2 <= THRESH and st2 in (3,4,5,6,7) and printed < 6:
                            op_st = op_verz = op_mom = None
                            if hist1:
                                op_verz, op_st, op_mom = hist1[-1]
                            # 打印命中点前15帧+本帧序列
                            print(f"\n--- seg{seg} 命中#{printed+1} (原厂verz={verz2:.2f} st={st2} mom={mom2} loes={loes2} | 油门Fahrerwunsch={gas}) ---")
                            print("  帧  原厂verz 原厂st 原厂mom 原厂loes | OP verz OP st OP mom")
                            seq = list(hist2)
                            for i,(v,s,mo,l) in enumerate(seq):
                                mark = " ←命中" if (v <= THRESH and i == len(seq)-1) else ""
                                print(f"  {i:>3}  {v:>7.2f}  {s:>4}  {mo:>5}  {l:>5}    |", mark)
                            print(f"  >> OP当前: verz={None if op_verz is None else round(op_verz,2)} st={op_st} mom={op_mom}")
                            hits += 1; printed += 1
                    elif c.src == 128:
                        st1 = extract(c.dat, 57, 3); verz1 = extract(c.dat, 32, 11)*0.005 - 7.22
                        mom1 = extract(c.dat, 16, 10)
                        hist1.append((verz1, st1, mom1))
                elif c.address == 128 and c.src == 0:
                    gas = extract(c.dat, 52, 10)  # MO_Mom_Fahrerwunsch
    except Exception as e:
        print(f"  {seg} 失败: {type(e).__name__}", flush=True)
    seg_min[seg] = round(mmin, 2)

print(f"\n=== 汇总: 命中{ROUTE} verz<={THRESH} 共 {hits} 处(每段最多6处) ===")
print("=== 各段 verz 最小值 <= -1.0 ===")
for k in sorted(seg_min, key=lambda x:int(x)):
    if seg_min[k] <= -1.0: print(f"  seg {k}: verz_min={seg_min[k]}")
