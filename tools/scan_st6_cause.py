#!/usr/bin/env python3
"""scan_st6_cause.py — 定位 bus2 ACC_05 st=6 直接原因
扫描 route 各段，找 bus2(原厂) st==6 事件，输出事件前~35帧逐帧对照：
  STOCK(原厂bus2) vs OP(bus0/128代发) 的 st/verz/mom/axG/loes/FV/FM/anh
  + 油门MO_Mom_Fahrerwunsch + 车速KBI_angez_Geschw
并统计: 每段 st6次数、OP st=4 vs 原厂 st=3 的不一致帧数
用法: python3 scan_st6_cause.py ROUTE
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
        'anh': extract(d,62,1), 'esp': extract(d,61,1),
    }

def fmt(r):
    if r is None: return "-"
    return f"st{r['st']}|v{r['verz']}|m{r['mom']}|ax{r['axg']}|l{r['loes']}|F{r['fv']}{r['fm']}|a{r['anh']}"

segs = sorted(glob.glob(f"{BASE}/{ROUTE}--*--*/rlog.zst"))
print(f"扫描 {ROUTE} 共 {len(segs)} 段, 定位 bus2 st=6 直接原因", flush=True)
total6 = 0
for sp in segs:
    seg = os.path.basename(os.path.dirname(sp)).split('--')[-1]
    buf = []; hit = 0; st6_cnt = 0; st_mismatch = 0
    last_gas = 0; last_v = 0
    try:
        for m in LogReader(sp):
            if m.which() != 'can': continue
            for c in m.can:
                src, addr = c.src, c.address
                bt = c.deprecated.busTime
                if addr == 128 and src == 0:
                    last_gas = extract(c.dat, 52, 10)
                elif addr == 779 and src == 0:
                    last_v = extract(c.dat, 48, 10) * 0.32
                elif addr == 269:
                    dec = dec269(bytes(c.dat))
                    buf.append((bt, src, dec, last_gas, last_v))
                    buf = buf[-40:]
                    if src == 2 and dec['st'] == 6:
                        st6_cnt += 1; total6 += 1
                        if hit < 4:
                            hit += 1
                            print(f"\n===== seg{seg} st=6事件#{hit} =====")
                            print(f"{'帧':>3} {'bus':>3} {'STOCK(bus2)':>34} {'OP(0/128)':>34} {'gas':>4} {'vkmh':>5}")
                            for i,(b2,s2,d2,g,vv) in enumerate(buf[-36:]):
                                stk = d2 if s2 == 2 else None
                                oo = d2 if s2 in (0,128) else None
                                tag = " <==6" if (stk and stk['st']==6) else ""
                                print(f"{i:>3} {s2:>3} {fmt(stk):>34} {fmt(oo):>34} {g:>4} {vv:>5.1f}{tag}")
                    # OP st=4 vs 原厂 st=3 不一致统计
                    if src in (0,128) and dec['st'] == 4:
                        for (_, s2, d2, _, _) in buf:
                            if s2 == 2 and d2['st'] == 3:
                                st_mismatch += 1
                                break
    except Exception as e:
        print(f"  {seg} 失败: {type(e).__name__} {e}", flush=True)
    print(f"[{seg}] st6次数={st6_cnt} OP4vs原厂3不一致帧={st_mismatch}", flush=True)
print(f"\n=== 汇总: {ROUTE} 总 st=6 事件 {total6} 次 ===")
