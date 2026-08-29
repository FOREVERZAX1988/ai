#!/usr/bin/env python3
"""corr_verz_mom_lag.py — axG 与 mom 时序相关性（同帧 + 滞后窗口）

回答: 原厂 ACC_05 内 verz(ACC_Verz_anf, 减速度请求) 与 mom(ACC_Momentenanforderung, 力矩请求)
是否存在直接函数关系（同帧线性），或时序关系（一方领先 k 帧）？

用法:
  python3 corr_verz_mom_lag.py 0000004e                # 指定 route 全部段
  python3 corr_verz_mom_lag.py 0000004e --seg 1 --seg 2  # 只扫指定段
  python3 corr_verz_mom_lag.py 0000004e --lagmax 12      # 滞后窗口 ±12 帧

输出: 分场景(巡航/加速/减速/超驰) 同帧 corr + 最佳滞后帧 corr
物理背景: verz 是减速度请求通道（默认0，减速时负值，超驰时正斜坡加速声明），
mom 是力矩请求通道（默认0，加速时发力）。两者互斥分工：加速靠 mom、减速靠 verz，
理论上无直接函数关系。
"""
import glob, os, sys, re
sys.path.insert(0, "/data/openpilot")
import numpy as np
from openpilot.tools.lib.logreader import LogReader

DBC = "/data/openpilot/opendbc_repo/opendbc/dbc/vw_mlb.dbc"
BASE = "/data/media/0/realdata"

def sigs():
    L = open(DBC, encoding="latin-1").read().splitlines()
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
    if not p:
        return None
    S = sigs(); rows = []; cs = {}
    for m in LogReader(p[0]):
        w = m.which()
        if w == 'carState':
            c = m.carState
            cs = {'v': float(c.vEgo), 'a': float(c.aEgo)}
        elif w == 'can':
            for c in m.can:
                if c.address == 269 and c.src == 2 and len(c.dat) >= 8:
                    d = bytes(c.dat)
                    st = int(gs(d, *S['ACC_Status_ACC']))
                    vz = gs(d, *S['ACC_Verz_anf'])
                    mom = gs(d, *S['ACC_Momentenanforderung'])
                    axg = gs(d, *S['ACC_ax_Getriebe'])
                    fv = int(gs(d, *S['ACC_Freigabe_Verzanf']))
                    fm = int(gs(d, *S['ACC_Freigabe_Momentenanf']))
                    rows.append([cs.get('v', 0), cs.get('a', 0), st, vz, mom, axg, fv, fm])
    return np.array(rows, dtype=float) if len(rows) > 100 else None

def analyze(A, label, lagmax):
    if A is None or len(A) < 100:
        print(f"[{label}] 样本不足"); return
    mom = A[:, 4]; verz = A[:, 3]; a = A[:, 1]; st = A[:, 2]
    scenes = {
        '巡航': (np.abs(a) < 0.3) & (st == 3),
        '加速fm': A[:, 7] == 1,
        '减速fv': (A[:, 6] == 1) | (A[:, 3] < -0.05),
        '超驰st4': st == 4,
    }
    for sn, mask in scenes.items():
        n = int(mask.sum())
        if n < 100:
            print(f"[{label}|{sn}] n={n} 样本不足(<100)"); continue
        m_ = mom[mask]; x_ = verz[mask]
        c0 = float(np.corrcoef(m_, x_)[0, 1])
        best = (0, c0)
        for lag in range(-lagmax, lagmax + 1):
            if lag == 0:
                continue
            if lag > 0:  # corr(mom[t], verz[t+lag]): verz 领先 mom
                mm, xx = m_[:len(m_)-lag], x_[lag:]
            else:        # axg 滞后 mom
                mm, xx = m_[-lag:], x_[:len(x_)+lag]
            if len(mm) < 100:
                continue
            c = float(np.corrcoef(mm, xx)[0, 1])
            if abs(c) > abs(best[1]):
                best = (lag, c)
        print(f"[{label}|{sn}] n={n} 同帧corr={c0:+.3f} | 最佳lag={best[0]:+d}帧 corr={best[1]:+.3f}"
              f"{' ← verz领先mom' if best[0]>0 else (' ← verz滞后mom' if best[0]<0 else '')}")

def main():
    args = sys.argv[1:]
    lagmax, segs, routes = 10, [], []
    i = 0
    while i < len(args):
        if args[i] == '--lagmax':
            lagmax = int(args[i+1]); i += 2
        elif args[i] == '--seg':
            segs.append(args[i+1]); i += 2
        else:
            routes.append(args[i]); i += 1
    if not routes:
        print(__doc__); sys.exit(1)
    for r in routes:
        if segs:
            seg_list = segs
        else:
            seg_list = sorted({os.path.basename(os.path.dirname(p)).split('--')[-1]
                               for p in glob.glob(f"{BASE}/{r}--*--*/rlog.zst")},
                              key=lambda x: int(x) if x.isdigit() else 99)
        for s in seg_list:
            A = load(r, s)
            if A is not None:
                analyze(A, f"{r}-seg{s}", lagmax)

if __name__ == '__main__':
    main()
