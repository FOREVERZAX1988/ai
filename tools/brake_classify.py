#!/usr/bin/env python3
"""brake_classify.py — braking输出(verz<0)健康度分类工具
================================================================
用途：分析一个route里OP发送的减速请求(verz<0)：
  1. 真减速（planner accel<-0.08，前车减速/切入的真实制动需求）
  2. 阈值抖动（accel在[-0.08,0)，planner几乎没要求减速——控制噪声，
     应被 braking 滞回[-0.08,-0.02] 吸收）
  3. 其他（停车保持 verz=-2.0 / gas透传 / 瞬间矛盾帧）

用法：
  python3 ai/tools/brake_classify.py 00000066
  python3 ai/tools/brake_classify.py 00000066 --seg 10
  python3 ai/tools/brake_classify.py 00000066 --min-frames 5

输出：
  braking帧占比 / 窗口分布 / 分类占比 / 典型窗口(含lead dRel/vRel) / 健康度建议

依赖：openpilot.tools.lib.logreader（设备环境）
"""
import sys, glob, argparse
sys.path.insert(0, '/data/openpilot')
from openpilot.tools.lib.logreader import LogReader


def gs(d, sl, ln, sc=1.0, of=0.0):
    if len(d) * 8 < sl + ln:
        return 0
    bi = sl // 8; bo = sl % 8
    v = int.from_bytes(d[bi:bi + (sl + ln + 7) // 8 + 1], 'little')
    return round(((v >> bo) & ((1 << ln) - 1)) * sc + of, 3)


def classify(route, seg_filter=None, min_frames=3, verbose=False):
    files = sorted(glob.glob(f'/data/media/0/realdata/{route}--*--*/rlog.zst'))
    if not files:
        print(f"❌ {route}: 无rlog段")
        sys.exit(2)
    if seg_filter is not None:
        files = [f for f in files if f.split('/')[-2][-2:] == seg_filter]
        if not files:
            print(f"❌ {route} seg{seg_filter}: 无文件")
            sys.exit(2)

    n_brake = 0; n_op = 0; wins = []; win = None
    v = 0.0; accel = 0.0; drel = None; vrel = None
    detail = []
    for f in files:
        seg = f.split('/')[-2][-2:]
        t0 = None
        for m in LogReader(f):
            if t0 is None:
                t0 = m.logMonoTime
            rel = (m.logMonoTime - t0) / 1e9
            w = m.which()
            if w == 'carState':
                v = round(m.carState.vEgo, 2)
            elif w == 'carControl':
                accel = round(m.carControl.actuators.accel, 3)
            elif w == 'radarState':
                lo = m.radarState.leadOne
                drel = round(lo.dRel, 1); vrel = round(lo.vRel, 2)
            if w != 'can':
                continue
            for c in m.can:
                if len(c.dat) < 8 or c.address != 0x10D or c.src != 128:
                    continue
                d = bytes(c.dat)
                verz = gs(d, 32, 11, 0.005, -7.22)
                n_op += 1
                if verz < 0:
                    n_brake += 1
                    if win is None:
                        win = {'seg': seg, 't0': rel, 't1': rel, 'acc': accel,
                               'd': drel, 'vrel': vrel, 'n': 1}
                    else:
                        win['t1'] = rel; win['n'] += 1
                        win['acc'] = min(win['acc'], accel)
                else:
                    if win is not None:
                        if win['n'] >= min_frames:
                            wins.append(win)
                            if len(detail) < 8:
                                detail.append((win, (drel, vrel, accel, v)))
                        win = None
        if verbose:
            print(f"  seg{seg} 完成", flush=True)
    if win is not None and win['n'] >= min_frames:
        wins.append(win)

    # 统计
    pct = n_brake * 100 // max(n_op, 1)
    print(f"\n===== {route} braking(verz<0) 健康度 =====")
    print(f"OP帧={n_op} braking帧={n_brake} ({pct}%) 窗口={len(wins)}")
    if wins:
        durs = [w['t1'] - w['t0'] for w in wins]
        print(f"窗口时长: min={min(durs):.1f}s 中位={sorted(durs)[len(durs)//2]:.1f}s max={max(durs):.1f}s")
    # 分类
    cat = {'真减速(accel<-0.08)': 0, '阈值抖动(-0.08<=accel<0)': 0, '其他(停车保持/透传)': 0}
    for w in wins:
        if w['acc'] < -0.08:
            cat['真减速(accel<-0.08)'] += 1
        elif w['acc'] < 0:
            cat['阈值抖动(-0.08<=accel<0)'] += 1
        else:
            cat['其他(停车保持/透传)'] += 1
    nw = max(len(wins), 1)
    print(f"分类: 真减速={cat['真减速(accel<-0.08)']}({cat['真减速(accel<-0.08)']*100//nw}%) "
          f"阈值抖动={cat['阈值抖动(-0.08<=accel<0)']}({cat['阈值抖动(-0.08<=accel<0)']*100//nw}%) "
          f"其他={cat['其他(停车保持/透传)']}({cat['其他(停车保持/透传)']*100//nw}%)")
    # 健康度
    jitter = cat['阈值抖动(-0.08<=accel<0)']
    if jitter / nw > 0.3:
        print("⚠️ 健康度：阈值抖动>30% —— braking滞回可能未生效，或planner accel噪声大（检查版本/坡度开关）")
    elif jitter / nw > 0.15:
        print("🟡 健康度：阈值抖动15-30% —— 可观察，滞回后应下降")
    else:
        print("✅ 健康度：阈值抖动<15% —— 减速输出基本是真实制动需求")
    print("\n=== 典型braking窗口(前8) ===")
    for w, ctx in detail:
        print(f"  seg{w['seg']} t={w['t0']:.1f}~{w['t1']:.1f}s 时长{w['t1']-w['t0']:.1f}s "
              f"minAccel={w['acc']:.2f} lead(d={ctx[0]},vRel={ctx[1]}) accel={ctx[2]} v={ctx[3]}")


def main():
    ap = argparse.ArgumentParser(description='braking输出健康度分类')
    ap.add_argument('route', help='route id，如 00000066')
    ap.add_argument('--seg', default=None, help='只分析某段，如 10 或 -5')
    ap.add_argument('--min-frames', type=int, default=3, help='窗口最短帧数(默认3=30ms)')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()
    classify(args.route, seg_filter=args.seg, min_frames=args.min_frames, verbose=args.verbose)


if __name__ == '__main__':
    main()
