#!/usr/bin/env python3
"""
scan_override_protocol.py — 原厂ACC超驰(st=4)切换点完整信号时序扫描
用法: python3 scan_override_protocol.py ROUTE_PREFIX [ROUTE_PREFIX2 ...]
例:   python3 scan_override_protocol.py 00000002 00000004
输出: 每个 st=3→4 切换点前后±20帧 的 verz/FV/FM/mom/axG/loes/st 序列
依赖: /data/openpilot/opendbc_repo/opendbc/dbc/vw_mlb.dbc (BO_269 帧内提取)
"""
import sys, os, re, glob
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

BASE = "/data/media/0/realdata"
DBC = "/data/openpilot/opendbc_repo/opendbc/dbc/vw_mlb.dbc"

def get_sigs():
    lines = open(DBC, encoding="latin-1").read().splitlines()
    s = next(i for i,l in enumerate(lines) if l.startswith('BO_ 269 '))
    e = next(i for i in range(s+1,len(lines)) if lines[i].startswith('BO_ '))
    blk = "\n".join(lines[s:e])
    out = {}
    for l in blk.splitlines():
        l = l.strip()
        m = re.match(r'^SG_ (\w+) : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)', l)
        if m:
            out[m.group(1)] = (int(m.group(2)), int(m.group(3)), m.group(5)=='-',
                               float(m.group(6)), float(m.group(7)))
    return out

def gs(dat, start, length, signed, scale=1.0, offset=0.0):
    if len(dat) <= (start+length-1)//8: return 0
    val=0
    for i in range(length):
        byte=(start+i)//8; bit=(start+i)%8
        if dat[byte] & (1<<bit): val |= (1<<i)
    if signed and val & (1<<(length-1)): val -= (1<<length)
    return val*scale+offset

def main(prefixes):
    S = get_sigs()
    fields = ['ACC_Status_ACC','ACC_Verz_anf','ACC_Freigabe_Verzanf',
              'ACC_Freigabe_Momentenanf','ACC_Momentenanforderung',
              'ACC_ax_Getriebe','ACC_Loeseanforderung']
    for pref in prefixes:
        segs = sorted(glob.glob(f"{BASE}/{pref}--*"))
        if not segs:
            print(f"[{pref}] 未找到段"); continue
        total_tx = 0
        for seg in segs:
            path = os.path.join(seg, "rlog.zst")
            if not os.path.exists(path): continue
            rname = os.path.basename(seg)
            try:
                lr = LogReader(path)
            except Exception as ex:
                print(f"[{rname}] 读取失败:{ex}"); continue
            prev_st = -1; buf = []
            tx = 0
            for msg in lr:
                if msg.which() != 'can': continue
                for c in msg.can:
                    if c.address == 269 and c.src == 2 and len(c.dat) >= 8:
                        d = bytes(c.dat)
                        st = int(gs(d, *S['ACC_Status_ACC']))
                        rec = {f: gs(d, *S[f]) for f in fields}
                        buf.append(rec); buf = buf[-45:]
                        if st == 4 and prev_st == 3:
                            tx += 1
                            mid = buf[-1]['ACC_Status_ACC']
                            # 打印前22帧(3→4)到进入4后几帧
                            print(f"\n[{rname}] 超驰切换#{tx}  (st3→4)")
                            for i, r in enumerate(buf[-24:]):
                                mark = "◀4" if i >= len(buf)-1-0 and r['ACC_Status_ACC']==4 else ""
                                print(f"  {i-23:+3d}nd st={r['ACC_Status_ACC']} verz={r['ACC_Verz_anf']:+.2f} "
                                      f"FV={r['ACC_Freigabe_Verzanf']} FM={r['ACC_Freigabe_Momentenanf']} "
                                      f"mom={r['ACC_Momentenanforderung']*10:.1f} axG={r['ACC_ax_Getriebe']:+.2f} "
                                      f"loes={r['ACC_Loeseanforderung']} {mark}")
                        prev_st = st
            total_tx += tx
            print(f"[{rname}] st→4切换 {tx} 次")
        print(f"[{pref}] 合计超驰切换 {total_tx} 次")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: scan_override_protocol.py ROUTE_PREFIX [...]"); sys.exit(1)
    main([a.lstrip('[').rstrip(']') for a in sys.argv[1:]])
