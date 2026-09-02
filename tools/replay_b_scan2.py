#!/usr/bin/env python3
"""replay_b_scan2.py — 稳健版 st6 残留 + 镜像窗口扫描（63/65）"""
import glob, os, sys
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

BASE = "/data/media/0/realdata"
def parse_acc05(d):
    if len(d) < 8: return None
    v = 0
    for i in range(3):
        b = (57+i)//8; bt = (57+i)%8
        if d[b] & (1<<bt): v |= (1<<i)
    return v  # ACC_Status_ACC

def gsv(d, sl, ln):
    v = 0
    for i in range(ln):
        b=(sl+i)//8; bt=(sl+i)%8
        if d[b]&(1<<bt): v|=(1<<i)
    return v

def seg_stats(route, seg, tag):
    p = glob.glob(f"{BASE}/{route}--*--{seg}/rlog.zst")
    if not p: 
        return "nomatch"
    st_cnt = {}
    first_st6 = None
    n = 0
    try:
        for m in LogReader(p[0]):
            if m.which() != 'can': continue
            for c in m.can:
                if c.address != 269 or len(c.dat) < 8: continue
                src = c.src
                if tag == 'stock' and src != 2: continue
                if tag == 'op' and src != 0: continue
                st = parse_acc05(bytes(c.dat))
                st_cnt[st] = st_cnt.get(st, 0) + 1
                n += 1
                if st == 6 and first_st6 is None:
                    first_st6 = n
    except Exception as e:
        return f"ERR {e}"
    s6 = st_cnt.get(6, 0)
    extra = f" | st6 首帧@{first_st6}" if s6 else ""
    srt = ",".join(f"{k}:{v}" for k,v in sorted(st_cnt.items()))
    return f"[seg{seg}] {tag}: frames={n} st{{{srt}}}{extra}"

def main():
    for route in ["00000063", "00000065"]:
        segs = sorted({os.path.basename(os.path.dirname(p)).split('--')[-1] for p in glob.glob(f"{BASE}/{route}--*--*/rlog.zst")}, key=lambda x:int(x))
        print(f"===== {route} ({len(segs)}段) =====")
        for s in segs:
            o = seg_stats(route, s, 'op')
            k = seg_stats(route, s, 'stock')
            print(f"  {o}")
            print(f"  {k}")

if __name__ == '__main__':
    main()
