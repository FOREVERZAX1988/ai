#!/usr/bin/env python3
"""scan_st7_edge.py — 定位原厂 st=7(不可逆故障) 上升沿
找 bus2 st 从非7→7 的时刻，打印前30帧 + 沿帧 + 后5帧，对比 OP(bus1/128) vs 原厂(bus2)。
用法: python3 scan_st7_edge.py ROUTE
"""
import sys, glob, os
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

ROUTE = sys.argv[1] if len(sys.argv) > 1 else "00000065"
BASE = "/data/media/0/realdata"

def extract(dat, start, length):
    val = 0
    for i in range(length):
        pos = start - i
        b = pos // 8; bit = pos % 8
        v = (dat[b] >> (7 - bit)) & 1 if b < len(dat) else 0
        val = (val << 1) | v
    return val

def dec269(d):
    return {
        'st': extract(d,57,3), 'verz': round(extract(d,32,11)*0.005-7.22,2),
        'mom': extract(d,16,10), 'axg': round(extract(d,48,9)*0.024-2.016,2),
        'loes': extract(d,43,1), 'fv': extract(d,13,1), 'fm': extract(d,12,1),
        'anh': extract(d,62,1),
    }

def fmt(r):
    if r is None: return "-"
    return f"st{r['st']}|v{r['verz']}|m{r['mom']}|ax{r['axg']}|l{r['loes']}|F{r['fv']}{r['fm']}|a{r['anh']}"

segs = sorted(glob.glob(f"{BASE}/{ROUTE}--*--*/rlog.zst"))
print(f"扫描 {ROUTE} 共 {len(segs)} 段, 定位 st=7(不可逆故障) 上升沿", flush=True)
tot = 0
for sp in segs:
    seg = os.path.basename(os.path.dirname(sp)).split('--')[-1]
    buf = []; prev_st2 = -1; edge = 0
    try:
        for m in LogReader(sp):
            if m.which() != 'can': continue
            for c in m.can:
                if c.address != 269: continue
                dec = dec269(bytes(c.dat))
                buf.append((c.src, dec)); buf = buf[-40:]
                if c.src == 2:
                    if prev_st2 != -1 and prev_st2 != 7 and dec['st'] == 7:
                        edge += 1; tot += 1
                        if edge <= 3:
                            print(f"\n===== seg{seg} st{prev_st2}->7 不可逆故障沿#{edge} =====")
                            print(f"{'帧':>3} {'bus':>4} {'STOCK(bus2)':>30} {'OP(bus1/128)':>30}")
                            for i,(s2,d2) in enumerate(buf[-30:]):
                                stk = d2 if s2 == 2 else None
                                oo = d2 if s2 in (1,128) else None
                                tag = " <==7" if (stk and stk['st'] == 7) else ""
                                print(f"{i:>3} {s2:>4} {fmt(stk):>30} {fmt(oo):>30}{tag}")
                    prev_st2 = dec['st']
    except Exception as e:
        print(f"  {seg} 失败: {type(e).__name__}", flush=True)
    print(f"[{seg}] st7上升沿={edge}", flush=True)
print(f"\n=== 汇总: {ROUTE} st=7(不可逆) 上升沿共 {tot} 次 ===")
