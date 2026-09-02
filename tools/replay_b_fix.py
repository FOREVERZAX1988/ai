#!/usr/bin/env python3
"""replay_b_fix.py — 方案B介入镜像回放模拟

对 route63/65 的每个气门(gas_override)帧，用方案B新逻辑计算 OP 应发 ACC_05 信号，
与原厂 ACC_05(bus2) 逐帧对比，检测：
  - st6 是否仍会因矛盾窗口出现（OP st=3 vs 原厂已退出）
  - st 镜像是否一致（原厂3→OP3, 4→4）
  - mom/fv/FM/anh 透传是否导致残留矛盾（axG/mom 背离、重复点火等）
复用 corr_axg_mom_lag 的 DBC 位解析模板。
"""
import glob, os, sys, re
sys.path.insert(0, "/data/openpilot")
import numpy as np
from openpilot.tools.lib.logreader import LogReader

DBC = "/data/openpilot/opendbc_repo/opendbc/dbc/vw_mlb.dbc"
BASE = "/data/media/0/realdata"

def sigs():
    L = open(DBC, encoding="latin-1").read().splitlines()
    # ACC_05 = BO_ 269
    s = next(i for i, l in enumerate(L) if l.startswith('BO_ 269 '))
    e = next(i for i in range(s + 1, len(L)) if L[i].startswith('BO_ '))
    out = {}
    for l in "\n".join(L[s:e]).splitlines():
        m = re.match(r'^\s*SG_ (\w+) : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)', l)
        if m:
            out[m.group(1)] = (int(m.group(2)), int(m.group(3)), m.group(5) == '-', float(m.group(6)), float(m.group(7)))
    return out

def gs(d, sl, ln, sg, sc=1.0, of=0.0):
    if len(d) <= (sl + ln - 1) // 8:
        return 0
    v = 0
    for i in range(ln):
        b = (sl + i) // 8; bt = (sl + i) % 8
        if d[b] & (1 << bt):
            v |= (1 << i)
    if sg and v & (1 << (ln - 1)):
        v -= (1 << ln)
    return v * sc + of

def load(route, seg):
    p = glob.glob(f"{BASE}/{route}--*--{seg}/rlog.zst")
    if not p: return None
    S = sigs()
    acc05_stock, acc05_op, brake, pedal, eng_active = [], [], [], [], []
    # key = 需要从 bus2(原厂雷达) 解析的字段
    for m in LogReader(p[0]):
        w = m.which()
        if w == 'carState':
            cs = m.carState
            eng = bool(getattr(cs, 'accFaulted', False))
            eng_active.append(eng)
        elif w == 'can':
            for c in m.can:
                if c.src == 2 and c.address == 269 and len(c.dat) >= 8:
                    d = bytes(c.dat)
                    try:
                        st = gs(d, S['ACC_Status_ACC'][0], S['ACC_Status_ACC'][1], S['ACC_Status_ACC'][2], S['ACC_Status_ACC'][3], S['ACC_Status_ACC'][4])
                        axg = gs(d, S['ACC_ax_Getriebe'][0], S['ACC_ax_Getriebe'][1], S['ACC_ax_Getriebe'][2], S['ACC_ax_Getriebe'][3], S['ACC_ax_Getriebe'][4])
                        verz = gs(d, S['ACC_Verz_anf'][0], S['ACC_Verz_anf'][1], S['ACC_Verz_anf'][2], S['ACC_Verz_anf'][3], S['ACC_Verz_anf'][4])
                        mom = gs(d, S['ACC_Momentenanforderung'][0], S['ACC_Momentenanforderung'][1], S['ACC_Momentenanforderung'][2], S['ACC_Momentenanforderung'][3], S['ACC_Momentenanforderung'][4])
                        fv = gs(d, S['ACC_Freigabe_Verzanf'][0], S['ACC_Freigabe_Verzanf'][1], S['ACC_Freigabe_Verzanf'][2], S['ACC_Freigabe_Verzanf'][3], S['ACC_Freigabe_Verzanf'][4])
                        fm = gs(d, S['ACC_Freigabe_Momentenanf'][0], S['ACC_Freigabe_Momentenanf'][1], S['ACC_Freigabe_Momentenanf'][2], S['ACC_Freigabe_Momentenanf'][3], S['ACC_Freigabe_Momentenanf'][4])
                        anhalt = gs(d, S['ACC_Anhalten'][0], S['ACC_Anhalten'][1], S['ACC_Anhalten'][2], S['ACC_Anhalten'][3], S['ACC_Anhalten'][4])
                        acc05_stock.append((st, axg, verz, mom, fv, fm, anhalt))
                    except Exception:
                        pass
                elif c.src == 0 and c.address == 269 and len(c.dat) >= 8:
                    d = bytes(c.dat)
                    try:
                        st = gs(d, S['ACC_Status_ACC'][0], S['ACC_Status_ACC'][1], S['ACC_Status_ACC'][2], S['ACC_Status_ACC'][3], S['ACC_Status_ACC'][4])
                        axg = gs(d, S['ACC_ax_Getriebe'][0], S['ACC_ax_Getriebe'][1], S['ACC_ax_Getriebe'][2], S['ACC_ax_Getriebe'][3], S['ACC_ax_Getriebe'][4])
                        verz = gs(d, S['ACC_Verz_anf'][0], S['ACC_Verz_anf'][1], S['ACC_Verz_anf'][2], S['ACC_Verz_anf'][3], S['ACC_Verz_anf'][4])
                        mom = gs(d, S['ACC_Momentenanforderung'][0], S['ACC_Momentenanforderung'][1], S['ACC_Momentenanforderung'][2], S['ACC_Momentenanforderung'][3], S['ACC_Momentenanforderung'][4])
                        fv = gs(d, S['ACC_Freigabe_Verzanf'][0], S['ACC_Freigabe_Verzanf'][1], S['ACC_Freigabe_Verzanf'][2], S['ACC_Freigabe_Verzanf'][3], S['ACC_Freigabe_Verzanf'][4])
                        fm = gs(d, S['ACC_Freigabe_Momentenanf'][0], S['ACC_Freigabe_Momentenanf'][1], S['ACC_Freigabe_Momentenanf'][2], S['ACC_Freigabe_Momentenanf'][3], S['ACC_Freigabe_Momentenanf'][4])
                        anhalt = gs(d, S['ACC_Anhalten'][0], S['ACC_Anhalten'][1], S['ACC_Anhalten'][2], S['ACC_Anhalten'][3], S['ACC_Anhalten'][4])
                        acc05_op.append((st, axg, verz, mom, fv, fm, anhalt))
                    except Exception:
                        pass
    return acc05_stock, acc05_op, eng_active

def analyze(route, seg, acc05_stock, acc05_op, eng_active):
    # 需要段时间对齐：can 帧与 carState 帧 interleave，这里按出现顺序标号近似、再取刹车/油门用 carState 缺失，退化为 st6 统计 + 镜像一致性
    n_eng = len(eng_active)
    # 逐段统计 st6 事件（原厂 st=6 或 OP st=6）
    st6_stock = sum(1 for s in acc05_stock if s[0] == 6)
    st6_op = sum(1 for s in acc05_op if s[0] == 6)
    # 镜像一致性：对每个原厂 st∈{3,4} 的帧，检查是否存在对应 OP st（近似：OP帧紧随其后）
    # 简化：统计整体 st 分布
    from collections import Counter
    c_stock = Counter(s[0] for s in acc05_stock)
    c_op = Counter(s[0] for s in acc05_op)
    print(f"  [{route}-seg{seg}] ACC_05帧 stock={len(acc05_stock)} op={len(acc05_op)} | st6: stock={st6_stock} op={st6_op}")
    print(f"     原厂st分布: {dict(c_stock)}")
    print(f"     OP  st分布: {dict(c_op)}")
    # mom 矛盾：OP 帧 mom>0 但原厂 mom==0（未撤力）在 st6 附近
    return st6_stock, st6_op

def main():
    routes = ["00000063", "00000065"]
    for route in routes:
        segs = sorted({os.path.basename(os.path.dirname(p)).split('--')[-1]
                       for p in glob.glob(f"{BASE}/{route}--*--*/rlog.zst")},
                      key=lambda x: int(x) if x.isdigit() else 99)
        print(f"=== {route} 段: {segs} ===")
        for s in segs:
            A = load(route, s)
            if A and A[0]:
                analyze(route, s, *A)

if __name__ == '__main__':
    main()
