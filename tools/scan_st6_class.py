#!/usr/bin/env python3
"""scan_st6_class.py — 分类 st=6 上升沿: st7→6(无效抖动) vs st3/4→6(控制中矛盾)
对 st3/4→6 的沿打印前20帧对比（直接原因），st7→6 只统计。
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
print(f"扫描 {ROUTE} 共 {len(segs)} 段, 分类 st=6 上升沿", flush=True)
t7 = t34 = 0
for sp in segs:
    seg = os.path.basename(os.path.dirname(sp)).split('--')[-1]
    buf = []; prev_st2 = -1; c7 = c34 = 0
    try:
        for m in LogReader(sp):
            if m.which() != 'can': continue
            for c in m.can:
                if c.address != 269: continue
                dec = dec269(bytes(c.dat))
                buf.append((c.src, dec)); buf = buf[-40:]
                if c.src == 2:
                    if prev_st2 != -1 and prev_st2 != 6 and dec['st'] == 6:
                        if prev_st2 == 7:
                            c7 += 1
                        elif prev_st2 in (3,4,5):
                            c34 += 1
                            print(f"\n===== seg{seg} st{prev_st2}→6 控制中矛盾沿#{c34} =====")
                            print(f"{'帧':>3} {'bus':>4} {'STOCK(bus2)':>30} {'OP(bus1/128)':>30}")
                            for i,(s2,d2) in enumerate(buf[-20:]):
                                stk = d2 if s2 == 2 else None
                                oo = d2 if s2 in (1,128) else None
                                tag = " <==沿" if (stk and stk['st'] == 6) else ""
                                print(f"{i:>3} {s2:>4} {fmt(stk):>30} {fmt(oo):>30}{tag}")
                    prev_st2 = dec['st']
    except Exception as e:
        print(f"  {seg} 失败: {type(e).__name__}", flush=True)
    t7 += c7; t34 += c34
    print(f"[{seg}] st7→6抖动={c7} st3/4→6矛盾={c34}", flush=True)
print(f"\n=== 汇总: {ROUTE} st7→6无效抖动={t7}, st3/4→6控制矛盾={t34} ===")
