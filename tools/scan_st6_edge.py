#!/usr/bin/env python3
"""scan_st6_edge.py — 定位 bus2 st=6 上升沿的直接原因
只关注 st 从非6→6 的转变时刻，打印转变前35帧（含正常st3/4期）+沿帧+后3帧，
对比 OP(bus1/128) vs 原厂(bus2) 的 st/verz/mom/axG/loes/FV/FM。
用法: python3 scan_st6_edge.py ROUTE
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
print(f"扫描 {ROUTE} 共 {len(segs)} 段, 定位 st=6 上升沿", flush=True)
tot_edge = 0
for sp in segs:
    seg = os.path.basename(os.path.dirname(sp)).split('--')[-1]
    buf = []; edge = 0; prev_st2 = -1; mismatch = 0
    try:
        for m in LogReader(sp):
            if m.which() != 'can': continue
            for c in m.can:
                src, addr = c.src, c.address
                if addr != 269: continue
                dec = dec269(bytes(c.dat))
                buf.append((src, dec))
                buf = buf[-45:]
                # OP st=4 vs 原厂 st=3 同窗不一致统计
                if src in (1,128) and dec['st'] == 4:
                    for (s2, d2) in buf:
                        if s2 == 2 and d2['st'] == 3:
                            mismatch += 1; break
                if src == 2:
                    if prev_st2 != -1 and prev_st2 != 6 and dec['st'] == 6:
                        edge += 1; tot_edge += 1
                        if edge <= 6:
                            print(f"\n===== seg{seg} st3/4→6上升沿#{edge} (前{len(buf)}帧缓存) =====")
                            print(f"{'帧':>3} {'bus':>4} {'STOCK(bus2)':>30} {'OP(bus1/128)':>30}")
                            for i,(s2,d2) in enumerate(buf[-38:]):
                                stk = d2 if s2 == 2 else None
                                oo = d2 if s2 in (1,128) else None
                                tag = " <==沿" if (stk and stk['st'] == 6) else ""
                                print(f"{i:>3} {s2:>4} {fmt(stk):>30} {fmt(oo):>30}{tag}")
                    prev_st2 = dec['st']
    except Exception as e:
        print(f"  {seg} 失败: {type(e).__name__} {e}", flush=True)
    print(f"[{seg}] st6上升沿={edge} OP4vs原厂3同窗={mismatch}", flush=True)
print(f"\n=== 汇总: {ROUTE} st=6 上升沿共 {tot_edge} 次 ===")
