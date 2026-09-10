#!/usr/bin/env python3
"""路试后一步复核（2026-09-10 会话四）：把 A2/A3 内部量逐帧落盘 + 打印判定指标。

口径与**上线代码同源**：B1 常量与 A2 阈值直接 import radard.py（不硬编码）。
逐帧输出列：t/idx/v/d_vis/d_stock/rel/w/w_vis/d_pred/融合dRel(实车落盘)/vLead对比
指标：①rel 分布与 A2 替换率 ②模式翻转/千帧（连续帧） ③d_pred vs 实车 radarState.dRel
     ④视觉-原厂(雷达)距离差（本会话关心的"视觉与雷达判定距离差多少"在**新路试**上的复现）

注意口径：本工具**不做拟合门控**（不卡 |v_vis−v_can|、不卡 100≤idx≤560、v_ego 取 carState 而非轮速），
所以中位数会与拟合文档（gated 干净集）有系统差；用它做**同一路线前后对比/趋势**，不要与文档基线逐个对齐。

用法：
  cd /data/openpilot && PYTHONPATH=/data/openpilot /usr/local/venv/bin/python \
      ai/tools/dump_a2_trace_0910.py [route 前缀, 默认取最新] [最多处理段数, 默认全部]
输出：CSV /tmp/a2trace_<route>.csv + 控制台汇总
"""
import os
import sys
import numpy as np

sys.path.insert(0, "/data/openpilot")
sys.path.insert(0, "/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader                      # noqa: E402
from openpilot.selfdrive.controls.radard import (MACAN_B1_T_A as A, MACAN_B1_T_B as B,  # noqa: E402
                                                 MACAN_A2_REL_TH as TH)
from opendbc.car.volkswagen.carcontroller import MACAN_DISP_REL_TH, CarController  # noqa: E402

BASE = "/data/media/0/realdata"


def segs_of(prefix=None):
  dirs = sorted(d for d in os.listdir(BASE) if os.path.isfile(f"{BASE}/{d}/rlog.zst"))
  if prefix:
    dirs = [d for d in dirs if d.startswith(prefix)]
  else:
    dirs = [d for d in dirs if d.startswith(str(max(int(d[:8]) for d in dirs)).zfill(8))] if dirs else []
  return dirs


def trace(seg):
  rows = []
  idx = 0; zl = 0; vlead = 0.0; v = 0.0; vis_d = None; vis_p = 0.0
  fused_d = 0.0; fused_p = False; fused_vl = 0.0
  try:
    for m in LogReader(f"{BASE}/{seg}/rlog.zst"):
      w = m.which()
      if w == "can":
        for c in m.can:
          if c.src != 2:
            continue
          d = c.dat
          if c.address == 780 and len(d) >= 7:
            idx = (d[3] | (d[4] << 8)) & 0x3FF; zl = (d[4] >> 5) & 7
          elif c.address == 804 and len(d) >= 7:
            x = ((d[5] | (d[6] << 8)) & 0x3FF) * 0.32
            vlead = x if x < 320 else 0.0
      elif w == "carState":
        v = float(m.carState.vEgo)
      elif w == "modelV2":
        ld = m.modelV2.leadsV3
        if len(ld) > 0 and len(ld[0].x) > 0:
          vis_p = float(ld[0].prob); vis_d = float(ld[0].x[0])
      elif w == "radarState":
        lo = m.radarState.leadOne
        fused_p = bool(lo.present); fused_d = float(lo.dRel); fused_vl = float(lo.vLead)
      if not (1 <= idx <= 1020 and vis_d is not None and vis_p > 0.5 and vis_d > 0 and v > 0):
        continue
      v_eff = max(v, 5.0)
      t_stock = A * idx + B
      d_stock = t_stock * v_eff
      rel = abs(vis_d - d_stock) / max(d_stock, 1.0)
      w = min(0.7 + (rel / TH) * 0.3, 1.0)
      df = 0.5 if vis_d < 15 else (1.17 if vis_d < 40 else (1.0 if vis_d < 60 else 0.83))
      w_vis = min((1.0 - w) * df, 0.5)
      d_pred = (1.0 - w_vis) * d_stock + w_vis * vis_d
      # 仪表显示源（第三处映射）：视觉换算 idx 与物理化迟滞判据
      vis_idx = CarController.op_lead_to_index(vis_d, v)
      disp_switch = abs(d_stock - vis_d) > MACAN_DISP_REL_TH * max(d_stock, 1.0)
      rows.append([t_stock, idx, v, vis_d, d_stock, rel, w, w_vis, d_pred, fused_d, int(fused_p),
                   fused_vl, vlead / 3.6 if vlead > 0 else 0.0, vis_idx, int(disp_switch), zl])
  except Exception as e:
    print(f"  [warn] {seg}: {e}", file=sys.stderr)
  return np.array(rows) if rows else np.zeros((0, 16))


HEAD = ("t_stock idx v_ego d_vis d_stock rel w w_vis d_pred fused_dRel fused_present "
        "fused_vLead vlead_ms vis_idx disp_switch zl").split()


def report(tag, X):
  if not len(X):
    print(f"{tag}: 无有效同目标帧"); return
  rel, d_pred, fused = X[:, 5], X[:, 8], X[:, 9]
  dv, ds = X[:, 3], X[:, 4]
  present = X[:, 10] > 0
  flip = (np.abs(np.diff(np.sign(rel - TH))) > 0).mean() * 1000 if len(rel) > 1 else 0.0
  print(f"{tag}: n={len(X)}")
  print(f"  A2 替换率(rel>{TH})={100 * np.mean(rel > TH):.1f}%   模式翻转={flip:.1f}/千帧")
  print(f"  视觉−雷达(B1)  中位={np.median(dv - ds):+.2f} m  中位绝对={np.median(np.abs(dv - ds)):.2f} m"
        f"  ≤5m={100 * np.mean(np.abs(dv - ds) <= 5):.1f}%")
  if present.any():
    e = np.abs(d_pred[present] - fused[present])
    print(f"  d_pred vs 实车 radarState.dRel（>0 帧 {present.sum()}）: 中位|Δ|={np.median(e):.2f} m  P90={np.percentile(e, 90):.2f} m")
  print(f"  仪表显示源判据触发率(|d_stock−d_vis|/d_stock>{MACAN_DISP_REL_TH})={100 * np.mean(X[:, 14] > 0):.1f}%")
  print(f"  idx 范围 {int(X[:, 1].min())}~{int(X[:, 1].max())}   v 范围 {X[:, 2].min():.1f}~{X[:, 2].max():.1f} m/s"
        f"   t_stock 范围 {X[:, 0].min():.2f}~{X[:, 0].max():.2f} s")


if __name__ == "__main__":
  pre = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] not in ("", "-") else None
  limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
  ss = segs_of(pre)
  if limit:
    ss = ss[:limit] if pre else ss[-limit:]
  print(f"[B1] A={A} B={B}  A2_REL_TH={TH}  DISP_REL_TH={MACAN_DISP_REL_TH}")
  print(f"段数 {len(ss)}（{ss[0] if ss else '-'} ... {ss[-1] if ss else '-'}）")
  all_rows = []
  for s in ss:
    X = trace(s)
    print(f"  {s}: {len(X)} 帧", flush=True)
    if len(X):
      all_rows.append(X)
  if not all_rows:
    print("没有可用帧：确认已路试并落盘 rlog，且原厂雷达/视觉同时有目标")
    sys.exit(0)
  ALL = np.vstack(all_rows)
  report("池化", ALL)
  # CSV 体积控制：整段 39 seg 的原始表 ~120MB，抽稀到 <=60k 行 + 紧凑格式
  step = max(1, len(ALL) // 60000)
  out = f"/tmp/a2trace_{pre or 'latest'}.csv"
  fmt = ["%.3f", "%d", "%.2f", "%.2f", "%.2f", "%.4f", "%.4f", "%.4f", "%.2f",
         "%.2f", "%d", "%.2f", "%.2f", "%d", "%d", "%d"]
  np.savetxt(out, ALL[::step], delimiter=",", header=",".join(HEAD), comments="", fmt=fmt)
  print(f"逐帧 CSV -> {out}")
  print("\n[路试判定清单] ① 视觉−雷达中位差应 ~1m 内（旧代码是 −7~−8m）")
  print("                ② 替换率 ~5-15%、模式翻转 <10/千帧（旧代码 35%/12+）")
  print("                ③ d_pred 与实车 radarState.dRel：高速段期望中位 |Δ| <2m；低速段（v<5 等效距离模型）")
  print("                   与 Kalman 平滑/目标切换会让它偏大，属已知口径差（看趋势不看绝对值）")
  print("                ④ 仪表车距条与实际跟车距离目视一致")
