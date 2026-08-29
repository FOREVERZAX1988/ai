#!/usr/bin/env python3
"""scan_st6_sig.py — st6 事件 OP帧vs原厂帧 三信号(verz/mom/axG)差异分析

用途: 定位 ACC_05 st=6 退出的信号级根因——对比原厂帧(CAN2, src=2)与 OP 代发帧
(CAN0, src=128)在 st6 前后窗口的 verz/mom/axG/fm/fv/anh/loes 差异。

用法:
  python3 scan_st6_sig.py 0000004e             # 扫 route 全部段的 st6 事件
  python3 scan_st6_sig.py 0000004e --seg 8 12  # 只扫指定段
  python3 scan_st6_sig.py 0000004e --window 12 # 事件前后窗口帧数(默认10)

输出: st6 事件列表 + 每个事件窗口内 原厂→OP 逐帧对比 + 最大差异汇总。
已知结论(2026-08-29): st6 根因=axG 执行反馈矛盾——原厂停车保持末尾发
axG=+1.3~+2.1(起步预告), OP 自算 axG 方向/幅值不同步(4e/4f 全部 4 个 st3→6
事件实锤: axGΔ 0.36~2.69)。verz 超驰矛盾已由超驰透传修复(adc8dabc)。
"""
import sys, glob, os
sys.path.insert(0, "/data/openpilot")
import numpy as np
from openpilot.tools.lib.logreader import LogReader

BASE = "/data/media/0/realdata"
S = {'st': (57, 3, False, 1.0, 0.0), 'verz': (32, 11, False, 0.005, -7.22),
     'mom': (16, 10, False, 1.0, 0.0), 'axg': (48, 9, False, 0.024, -2.016),
     'fv': (13, 1, False, 1.0, 0.0), 'fm': (12, 1, False, 1.0, 0.0),
     'anh': (62, 1, False, 1.0, 0.0), 'loes': (43, 1, False, 1.0, 0.0)}

def gs(d, sl, ln, sg, sc=1.0, of=0.0):
    if len(d) <= (sl + ln - 1) // 8: return 0
    v = 0
    for i in range(ln):
        b = (sl + i) // 8; bt = (sl + i) % 8
        if d[b] & (1 << bt): v |= (1 << i)
    if sg and v & (1 << (ln - 1)): v -= (1 << ln)
    return v * sc + of

def load_pair(route, seg):
    p = glob.glob(f"{BASE}/{route}--*--{seg}/rlog.zst")
    if not p: return None, None
    S_f, O_f = [], []
    for m in LogReader(p[0]):
        if m.which() != 'can': continue
        t = m.logMonoTime
        for c in m.can:
            if c.address == 269 and len(c.dat) >= 8:
                d = bytes(c.dat)
                r = [t, int(gs(d, *S['st'])), gs(d, *S['verz']), gs(d, *S['mom']), gs(d, *S['axg']),
                     int(gs(d, *S['fv'])), int(gs(d, *S['fm'])), int(gs(d, *S['anh'])), int(gs(d, *S['loes']))]
                if c.src == 2: S_f.append(r)
                elif c.src == 128: O_f.append(r)
    return (np.array(S_f) if len(S_f) > 10 else None), (np.array(O_f) if len(O_f) > 10 else None)

def scan_route(route, segs, window):
    for seg in segs:
        S_f, O_f = load_pair(route, seg)
        if S_f is None: continue
        evts = []
        for k in range(1, len(S_f)):
            if S_f[k, 1] == 6 and S_f[k-1, 1] != 6:
                evts.append((k, int(S_f[k-1, 1])))
        if not evts: continue
        print(f"\n===== {route}-seg{seg}: st6 事件 {len(evts)} 个 =====")
        for k, s_from in evts:
            print(f"\n--- st6 @帧{k} (从 st{s_from} 进入) ---")
            lo, hi = max(0, k-window), min(len(S_f), k+3)
            dvs, das, dms = [], [], []
            for i in range(lo, hi):
                sr = S_f[i]
                j = int(np.argmin(np.abs(O_f[:, 0] - sr[0]))) if O_f is not None else -1
                or_ = O_f[j] if j >= 0 else np.zeros(9)
                mk = " <== st6" if int(sr[1]) == 6 else ""
                print(f"  i={i}{mk} 原厂: st={int(sr[1])} verz={sr[2]:+.3f} mom={sr[3]:.0f} axG={sr[4]:+.3f} fm={int(sr[5])} fv={int(sr[6])} anh={int(sr[7])} loes={int(sr[8])}")
                print(f"        OP : st={int(or_[1])} verz={or_[2]:+.3f} mom={or_[3]:.0f} axG={or_[4]:+.3f} fm={int(or_[5])} fv={int(or_[6])} anh={int(or_[7])} loes={int(or_[8])}")
                if j >= 0:
                    dvs.append(or_[2]-sr[2]); das.append(or_[4]-sr[4]); dms.append(or_[3]-sr[3])
                if int(sr[1]) == 6: break
            if dvs:
                print(f"  窗口差异: verzΔ[{min(dvs):+.3f},{max(dvs):+.3f}] axGΔ[{min(das):+.3f},{max(das):+.3f}] momΔ[{min(dms):+.0f},{max(dms):+.0f}]")

def main():
    args = sys.argv[1:]
    window, segs, routes = 10, [], []
    i = 0
    while i < len(args):
        if args[i] == '--window':
            window = int(args[i+1]); i += 2
        elif args[i] == '--seg':
            segs = [s for s in args[i+1:] if not s.startswith('--')]; break
        else:
            routes.append(args[i]); i += 1
    if not routes:
        print(__doc__); sys.exit(1)
    for r in routes:
        if segs:
            scan_route(r, segs, window)
        else:
            all_segs = sorted({os.path.basename(os.path.dirname(p)).split('--')[-1]
                               for p in glob.glob(f"{BASE}/{r}--*--*/rlog.zst")},
                              key=lambda x: int(x) if x.isdigit() else 99)
            scan_route(r, all_segs, window)

if __name__ == '__main__':
    main()
