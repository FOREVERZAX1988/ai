"""场景表：Macan 融合模式下仪表 ACC_Abstandsindex 的显示源判定（真实 CarController）。

判定代码位置：opendbc/car/volkswagen/carcontroller.py 约 672-742（HUD 块内 else 分支）
  radar_valid = 0 < stock_lead_distance < 1021
  if radar_valid and not disp_src_radar:   # 视觉源中
      if vis_raw == 0 or |d_stock - op_drel| > 0.30 * d_stock: disp_src_radar = True
  elif not radar_valid: disp_src_radar = False     # 只有这一条能把 latch 复位
  use_radar = radar_valid and disp_src_radar
运行：python3 ai/tools/_probe_macan_disp.py
"""
import sys
sys.path.insert(0, '/data/openpilot')
sys.path.insert(0, '/data/openpilot/ai/tools')
import macan_disp_lib as L

V = 20.0
cc, CP = L.build_cc()


def run(tag, sched, frames=None):
  L.reset(cc)
  frames = frames or len(sched)
  last = sched[-1]
  out = []
  for i in range(frames):
    stock, drel = sched[i] if i < len(sched) else last
    ab, rele, latch = L.step(cc, V, stock, 1 if stock else 0, drel, 15.0, 0.0, i)
    out.append((ab, latch, stock, L.idx_of(drel, V) if drel > 0 else 0))
  print('--- %s ---' % tag)
  print('  逐帧: ' + ' '.join('%d%s' % (o[0], 'L' if o[1] else '') for o in out[:14]) + (' ...' if len(out) > 14 else ''))
  print('  末帧 发出=%d (原厂=%d 融合=%d) latch=%s' % (out[-1][0], out[-1][2], out[-1][3], out[-1][1]))
  return out


# 20m/s 下 idx=400 等价 78.4m
run('S1 两源一致 (原厂 78.4m / 融合 78m)', [(400, 78.0)] * 10)
run('S2 两源偏离>30% (原厂 78.4m / 融合 40m)', [(400, 40.0)] * 10)
run('S3 中间 1 帧融合缺失, 之后恢复', [(400, 78.0)] * 5 + [(400, 0.0)] + [(400, 78.0)] * 12)
run('S4 原厂无目标, 融合有 78m', [(0, 78.0)] * 10)
run('S5 开头 3 帧融合缺失, 之后恢复', [(400, 0.0)] * 3 + [(400, 78.0)] * 15)
