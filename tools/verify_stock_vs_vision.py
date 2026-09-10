#!/usr/bin/env python3
"""# 验证 新公式stock距离 vs 视觉判定 谁准（2026-09-10）
核心问题：新线性公式 t=0.008718*idx+1.0178 把原厂距离放大了（idx>=100 比旧表远15~42%）。
视觉 lead 是独立信号。要判断"新公式是否比旧表准、视觉该信多少"，
必须用 INDEPENDENT 真值：真实雷达轨道（radar=True, modelProb>=0.9）的 dRel，
以及时距法 d=t_set*v 交叉。

三距同帧对比：
  d_stock_new  = 新公式 (0.008718*idx+1.0178)*max(v,5)
  d_stock_old  = 旧表 interp
  d_vis        = modelV2.leadsV3[0].x[0]（纯视觉）
  d_radar_true = radarState.leadOne.dRel，仅当 radar=True 且 modelProb>=0.9（真实雷达轨道，真值级）

判定：在雷达真值帧上，|d_stock_new - d_radar_true| vs |d_vis - d_radar_true| 谁小，
就知道区分"新公式准"还是"视觉准"。

用法：/usr/local/venv/bin/python3 ai/tools/verify_stock_vs_vision.py
"""
import sys, glob, os
sys.path.insert(0, '/data/openpilot/openpilot')
import numpy as np
from openpilot.tools.lib.logreader import LogReader

SEGS = list(range(19, 27))  # 0004 高速段 seg19-26
ROUTE = '00000004--915ebf086f--'

# ---- 旧表（radard.py _macan_abstands_t/_idx，保存副本）----
OLD_T = [0.81,0.81,0.81,0.81,0.81,0.785,0.804,0.822,0.837,0.872,0.942,0.932,0.899,0.978,1.025,1.14,1.168,1.185,1.203,1.275,1.288,1.364,1.422,1.439,1.459,1.505,1.571,1.616,1.682,1.708,1.766,1.801,1.828,1.869,1.933,2.0,2.028,2.091,2.12,2.17,2.246,2.24,2.351,2.353,2.394,2.435,2.467,2.497,2.553,2.635,2.653,2.711,2.774,2.823,2.923,2.968,3.031,3.075,3.121,3.128,3.197,3.263,3.249,3.221,3.299,3.398,3.472,3.435,3.37,3.531,3.619,3.628,3.684,3.826,3.726,3.778,3.884,3.925,3.955,3.955,4.074,4.038,4.065,3.966,4.014,4.154,4.193,4.216,4.406,4.453,4.301,4.438,4.562,4.482,4.512,4.587,4.71,4.802,4.565,4.708,4.835,4.974,4.654,4.799,4.81,5.048,4.816,5.052,5.098,5.015,5.237,5.364,5.606,5.354,5.336,5.782,5.384,5.474,5.536,5.604,5.377,5.619,5.587,5.762,5.787,5.909,5.862,6.202,6.331,6.144,5.986,5.941,5.893,6.144,6.061,6.458,6.146,6.397,6.59,6.58,6.536,6.392,6.494,6.0,6.94,6.0,6.0,6.0,6.0,7.149,6.0,6.0,6.0]
OLD_IDX = [27,32,37,42,47,52,57,62,67,72,77,82,87,92,97,102,107,112,117,122,127,132,137,142,147,152,157,162,167,172,177,182,187,192,197,202,207,212,217,222,227,232,237,242,247,252,257,262,267,272,277,282,287,292,297,302,307,312,317,322,327,332,337,342,347,352,357,362,367,372,377,382,387,392,397,402,407,412,417,422,427,432,437,442,447,452,457,462,467,472,477,482,487,492,497,502,507,512,517,522,527,532,537,542,547,552,557,562,567,572,577,582,587,592,597,602,607,612,617,622,627,632,637,642,647,652,657,662,667,672,677,682,687,692,697,702,707,712,717,722,727,732,737,742,747,752,757,762,767,772,777,780,1021]

def old_idx_to_t(idx):
    idx = max(min(idx, 1021), 27)
    return float(np.interp(idx, OLD_IDX, OLD_T))

def new_idx_to_t(idx):
    if idx < 100: return 0.8
    if idx > 560: return 6.0
    return 0.008718 * idx + 1.0178

def collect():
    """(v, idx, d_vis) 帧，以及带雷达真值的帧 (v, idx, d_vis, d_radar_true)"""
    all_frames = []      # (v, idx, d_stock_new, d_stock_old, d_vis)
    radar_true = []      # (idx, v, d_vis, d_radar_true) radar=True 帧
    for seg in SEGS:
        f = f'/data/media/0/realdata/{ROUTE}{seg}/rlog.zst'
        if not os.path.exists(f):
            print(f'  seg{seg}: missing', flush=True); continue
        cur_idx = 0; cur_v = 0.0
        try:
            for m in LogReader(f):
                w = m.which()
                if w == 'can':
                    for c in m.can:
                        if c.src == 2 and c.address == 780 and len(c.dat) >= 7:
                            cur_idx = (c.dat[3] | (c.dat[4] << 8)) & 0x3FF
                elif w == 'carState':
                    cur_v = float(m.carState.vEgo)
                elif w == 'modelV2':
                    ld = m.modelV2.leadsV3
                    if len(ld) == 0 or len(ld[0].x) == 0: continue
                    p = float(ld[0].prob); dv = float(ld[0].x[0])
                    if p < 0.5 or not (0 < cur_idx < 1021) or cur_v < 0.5: continue
                    t_new = new_idx_to_t(cur_idx); t_old = old_idx_to_t(cur_idx)
                    vv = max(cur_v, 5.0)
                    d_new = t_new * vv; d_old = t_old * vv
                    if 2.0 < d_new < 300:
                        all_frames.append((cur_v, cur_idx, d_new, d_old, dv))
                elif w == 'radarState':
                    lo = m.radarState.leadOne
                    if not lo.present or not lo.radar: continue
                    if lo.modelProb < 0.9: continue
                    if not (0 < cur_idx < 1021) or cur_v < 1.0: continue
                    radar_true.append((cur_idx, cur_v, dv, float(lo.dRel)))
        except Exception as e:
            print(f'  seg{seg} err {e}', flush=True)
    return all_frames, radar_true

if __name__ == '__main__':
    print('收集 0004 高速段三距帧 + 雷达真值帧...', flush=True)
    allf, rt = collect()
    print(f'三距帧={len(allf)}  雷达真值帧(radar=True,prob>=0.9)={len(rt)}', flush=True)
    if len(allf) < 500 or len(rt) < 10:
        print('样本不足'); sys.exit(1)

    a = np.array(allf)  # (v,idx,d_new,d_old,d_vis)
    print('\n=== 全体三距（新公式 vs 旧表 vs 视觉）===')
    print(f'{"量":<16}{"中位(m)":>10}{"mean(m)":>10}')
    for nm, col in [('d_stock_new',2),('d_stock_old',3),('d_vis',4)]:
        print(f'{nm:<16}{np.median(a[:,col]):>10.2f}{np.mean(a[:,col]):>10.2f}')
    dv = a[:,4]; dn = a[:,2]; d_o = a[:,3]
    print(f'\n视觉-新公式 中位偏 = {np.median(dv-dn):+.2f}m  mean={np.mean(dv-dn):+.2f}m')
    print(f'新公式-旧表 中位偏 = {np.median(dn-d_o):+.2f}m  mean={np.mean(dn-d_o):+.2f}m')

    # 按原厂距离分段
    print('\n=== 分段偏差（视觉 vs 新公式stock）===')
    edges = [0,15,25,40,60,90,130,300]
    print(f'{"段(m)":>8}{"n":>6}{"vis-stock(中位)":>14}{"vis_rmse":>10}')
    for i in range(len(edges)-1):
        lo,hi = edges[i],edges[i+1]
        msk = (dn>=lo)&(dn<hi)
        if msk.sum()<20: continue
        b=np.median(dv[msk]-dn[msk]); rm=np.sqrt(np.mean((dv[msk]-dn[msk])**2))
        print(f'{lo:>4}-{hi:<4}{msk.sum():>6}{b:>+12.2f}{rm:>10.2f}')

    # 雷达真值判定
    print('\n=== 雷达真值帧判定（谁更接近真值，idx + 速度带参）===')
    r = np.array(rt)  # (idx,v,d_vis,d_radar_true)
    d_true = r[:,3]; dvr = r[:,2]; 
    dnr = np.array([new_idx_to_t(i) for i in r[:,0]]) * np.maximum(r[:,1],5.0)
    dor = np.array([old_idx_to_t(i) for i in r[:,0]]) * np.maximum(r[:,1],5.0)
    print(f'{"模型":<14}{"MAD(m)":>9}{"RMSE(m)":>9}{"偏(m)":>9}')
    for nm, d in [('新公式',dnr),('旧表',dor),('视觉',dvr)]:
        mad=np.median(np.abs(d-d_true)); rm=np.sqrt(np.mean((d-d_true)**2)); b=np.median(d-d_true)
        print(f'{nm:<14}{mad:>9.2f}{rm:>9.2f}{b:>+9.2f}')
    # 谁胜出
    err_new=np.abs(dnr-d_true); err_vis=np.abs(dvr-d_true); err_old=np.abs(dor-d_true)
    win_new=np.mean(err_new<err_vis)*100
    win_old=np.mean(err_old<err_vis)*100
    print(f'\n新公式比视觉更接近真值的帧占比: {win_new:.1f}%')
    print(f'旧表比视觉更接近真值的帧占比: {win_old:.1f}%')
    # 真值帧上新公式距离域
    print(f'\n真值帧 距离范围: 新公式 {np.percentile(dnr,10):.1f}-{np.percentile(dnr,90):.1f}m, '
          f'视觉 {np.percentile(dvr,10):.1f}-{np.percentile(dvr,90):.1f}m, '
          f'真值 {np.percentile(d_true,10):.1f}-{np.percentile(d_true,90):.1f}m')
    np.save('/data/openpilot/ai/tools/verify_stock_vs_vision.npy', np.array(rt, dtype=object))
    print('\n已存 radar 真值帧 -> verify_stock_vs_vision.npy')
