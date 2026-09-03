#!/usr/bin/env python3
"""
model_baseline.py — 模型行为基线评测（切换模型后用同一路线对比）

用法:
  python3 model_baseline.py                  # 最近route(全部段, rlog)
  python3 model_baseline.py 0000006c         # 指定route
  python3 model_baseline.py 0000006c --segs 5
  python3 model_baseline.py 0000006c --qlog  # 快速版(无lead指标)

指标(衡量"模型给代码的输入质量", 与车型执行层无关):
  1. vT抖动 : longitudinalPlanSP.vTarget 帧间跳变 — 曲率预测噪声代理
     (vTarget由模型曲率限速算出; 抖动大=曲率预测噪声大→SCC弯道减速会晃)
  2. lead稳 : radarState.leadOne present翻转 + dRel跳变 — 前车跟踪稳定性
     (翻转/跳变频繁=视觉lead不稳→雷达融合负担大)
  3. aT阶跃 : longitudinalPlan.aTarget 帧间跳变 — 减速命令阶跃性
     (>0.5m/s²跳变是verz桥要柔化的对象)
  4. sccVision%: 源为sccVision的plan占比 — 弯道限速激活频率

输出: 表格 + JSON存档(ai/tools/model_baseline_results/)
对比: 换模型后跑同一路线再跑一次, 对比两次JSON(结果自带模型名)
"""
import os, glob, json, time, argparse
from openpilot.tools.lib.logreader import LogReader

ROOT = '/data/media/0/realdata'
OUT = '/data/openpilot/ai/tools/model_baseline_results'
LDR = None  # lead dRel上一值


def current_model_short():
    # 运行模型 = ModelManager_ActiveBundle(存在=自定义激活); 无=固件默认(stock)
    try:
        raw = open('/data/params/d/ModelManager_ActiveBundle', 'rb').read()
        if raw and len(raw) > 2:
            d = json.loads(raw)
            return d.get('short_name', 'custom') + '(激活)'
        d = json.load(open('/data/params/d/ModelManager_ModelsCache', 'rb'))
        fav = open('/data/params/d/ModelManager_Favs', 'rb').read().decode().strip()
        for b in d.get('bundles', []):
            if b.get('ref', '').startswith(fav[:25]):
                return 'default(stock)——fav:' + b.get('short_name', '?')
    except Exception:
        pass
    return 'default(stock)'


def list_segs(prefix):
    allr = sorted(glob.glob(ROOT + '/*--*--*'))
    hit = [os.path.basename(d) for d in allr
           if (prefix and (os.path.basename(d).startswith(prefix))) or (not prefix)]
    if not hit and prefix:
        base = prefix.split('--')[0]
        hit = [os.path.basename(d) for d in allr if os.path.basename(d).startswith(base)]
    if not hit:
        print(f"无匹配route: {prefix}")
        sys.exit(1)
    return sorted(hit)


def scan_seg(path, use_qlog):
    st = dict(sec=0.0, vt_d05=0, vt_pk=[], lp_flip=0, lp_jump=0,
              lp_on=0, lp_n=0, at_jump=0, at_max=0.0,
              scc_n=0, plan_n=0)
    lvT = lDRv = None
    lp_prev = None
    lAT = None
    t0 = None
    tp0 = tpn = None  # 首尾plan时间(有效活动跨度, 剔除熄火gap)
    for m in LogReader(path):
        t = m.logMonoTime / 1e9
        if t0 is None:
            t0 = t
        tt = t - t0
        w = m.which()
        try:
            if w == 'longitudinalPlanSP':
                p = m.longitudinalPlanSP
                st['plan_n'] += 1
                if tp0 is None:
                    tp0 = tt
                tpn = tt
                vt = float(p.vTarget)
                if lvT is not None:
                    dv = abs(vt - lvT)
                    if dv > 0.5:
                        st['vt_d05'] += 1
                    st['vt_pk'].append(dv)
                lvT = vt
                try:
                    src = str(p.longitudinalPlanSource).lower()
                    if 'sccvision' in src:
                        st['scc_n'] += 1
                except Exception:
                    pass
            elif w == 'longitudinalPlan':
                at = float(m.longitudinalPlan.aTarget)
                if lAT is not None:
                    da = abs(at - lAT)
                    if da > 0.5:
                        st['at_jump'] += 1
                    st['at_max'] = max(st['at_max'], da)
                lAT = at
            elif w == 'radarState' and not use_qlog:
                ld = m.radarState.leadOne
                pr = bool(ld.present)
                st['lp_n'] += 1
                if pr:
                    st['lp_on'] += 1
                if lp_prev is not None and pr != lp_prev:
                    st['lp_flip'] += 1
                lp_prev = pr
                if pr:
                    dr = float(ld.dRel)
                    if lDRv is not None and abs(dr - lDRv) > 5.0:
                        st['lp_jump'] += 1
                    lDRv = dr
        except Exception:
            pass
        if tp0 is not None and tpn is not None and (tpn - tp0) > 1:
            st['sec'] = tpn - tp0  # plan有效活动跨度
        elif st['sec'] == 0.0:
            st['sec'] = tt
    if st['vt_pk']:
        st['vt_pk'].sort()
        st['vt_p95'] = st['vt_pk'][int(len(st['vt_pk']) * 0.95)]
    else:
        st['vt_p95'] = 0.0
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('route', nargs='?', default=None)
    ap.add_argument('--segs', type=int, default=0)
    ap.add_argument('--qlog', action='store_true')
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    if args.route is None:
        bases = sorted(set(os.path.basename(d).split('--')[0] for d in glob.glob(ROOT + '/*--*--*')))
        segs = list_segs(bases[-1] if bases else None)
        route = bases[-1] if bases else '?'
    else:
        segs = list_segs(args.route)
        route = args.route.split('--')[0]
    if args.segs > 0:
        segs = segs[:args.segs]
    ext = 'qlog.zst' if args.qlog else 'rlog.zst'
    paths = [os.path.join(ROOT, s, ext) for s in segs if os.path.exists(os.path.join(ROOT, s, ext))]
    if not paths:
        print("无数据文件"); return

    model = current_model_short()
    print(f"模型: {model}  route: {route}  段数: {len(paths)} ({'qlog' if args.qlog else 'rlog'})")
    print(f"{'seg':>5} {'时长s':>6} {'vT>0.5':>7} {'vTP95':>6} {'aT>0.5':>7} {'aTmax':>6} "
          f"{'lead翻':>6} {'lead跳':>6} {'sccV%':>6}")
    per = []
    ag = dict(sec=0, vt=0, at=0, lf=0, lj=0)
    for p in paths:
        seg = p.split('--')[-1].split('/')[0]
        s = scan_seg(p, args.qlog)
        scc = (s['scc_n'] / s['plan_n'] * 100) if s['plan_n'] else 0
        print(f"{seg:>5} {s['sec']:6.0f} {s['vt_d05']:7.0f} {s['vt_p95']:6.2f} {s['at_jump']:7.0f} "
              f"{s['at_max']:6.2f} {s['lp_flip']:6.0f} {s['lp_jump']:6.0f} {scc:5.1f}")
        per.append(dict(seg=seg, sec=s['sec'], model=model, vt_d05=s['vt_d05'],
                        vt_p95=s['vt_p95'], at_jump=s['at_jump'], at_max=s['at_max'],
                        lead_flip=s['lp_flip'], lead_jump=s['lp_jump'], scc_pct=scc))
        ag['sec'] += s['sec']; ag['vt'] += s['vt_d05']; ag['at'] += s['at_jump']
        ag['lf'] += s['lp_flip']; ag['lj'] += s['lp_jump']
    mn = max(ag['sec'] / 60, 0.1)
    print("-" * 72)
    print(f"合计 {ag['sec']:.0f}s | vT跳 {ag['vt']:.0f}({ag['vt']/mn:.1f}/min) | "
          f"aT跳 {ag['at']:.0f}({ag['at']/mn:.1f}/min) | lead翻 {ag['lf']} | lead跳 {ag['lj']}")
    out = dict(route=route, model=model, timestamp=time.strftime('%Y%m%d-%H%M'),
               source='qlog' if args.qlog else 'rlog', segments=per)
    fn = os.path.join(OUT, f"{route}_{model}_{out['timestamp']}.json")
    json.dump(out, open(fn, 'w'), indent=1)
    print(f"已存: {fn}")


if __name__ == '__main__':
    main()
