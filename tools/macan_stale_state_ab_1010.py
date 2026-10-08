#!/usr/bin/env python3
"""Macan 融合「状态复位」A/B 回放 (2026-10-10)

目的：量化「目标丢失后不复位 => 新目标沿用旧目标距离」在实车 route 上的footprint。

方法（自验证设计）：
  recorded radarState.leadOne.dRel 是**当次行驶里旧代码（无复位）的真实输出**。
  于是回放两条分支，用同一份输入：
    A) 旧行为：lead 丢失时保留 _macan_smooth / _macan_last_fused（bug）
    B) 新行为：lead 丢失/换人时复位并重新播种（本次修复）
  校验点：A 必须能复现 recorded dRel（否则模型不忠实，B 不可信）。

用法: /usr/local/venv/bin/python ai/tools/macan_stale_state_ab_1010.py <route> [seg ...]
"""
import sys
import numpy as np

sys.path.insert(0, "/data/openpilot/openpilot")
sys.path.insert(0, "/data/openpilot")
from openpilot.common.filter_simple import FirstOrderFilter           # noqa: E402
from openpilot.selfdrive.controls.radard import (                     # noqa: E402
  MACAN_B1_T_A, MACAN_B1_T_B, MACAN_FUSE_REL_GATE, MACAN_FUSE_MIN_GAP, MACAN_FUSE_V_MAX_W,
  MACAN_VISION_PROB_MIN, MACAN_SMOOTH_RC, MACAN_RATE_MIN_STEP, MACAN_RATE_VFACTOR,
  MACAN_RESEED_MIN_JUMP, MACAN_RESEED_STEP_FACTOR, RADAR_TO_CAMERA, DT_MDL,
)
from openpilot.tools.lib.logreader import LogReader                   # noqa: E402

REALDATA = "/data/media/0/realdata"
HYST_WIN = 0.6


def t_from_idx(idx):
  return MACAN_B1_T_A * idx + MACAN_B1_T_B


def idx_to_drel(idx, v_ego):
  return t_from_idx(idx) * (v_ego if v_ego > 5.0 else 5.0)


def parse(seg):
  """逐帧(以 modelV2 为节拍, 与 radard 同频)抽取融合所需输入。"""
  rows = []
  idx = 0
  spd = 0.0
  v_ego = 0.0
  meta = {"commit": "?", "branch": "?", "fusion_param": "?"}
  for msg in LogReader(f"{REALDATA}/{seg}/rlog.zst"):
    w = msg.which()
    if w == "initData":
      try:
        raw = {str(k): v for k, v in msg.initData.to_dict().items()}
        flat = {k.lower(): str(v) for k, v in raw.items()}
        meta["commit"] = flat.get("gitcommit", "?")[:8]
        meta["branch"] = flat.get("gitbranch", "?")
        meta["fusion_param"] = flat.get("macanradarfusion", flat.get("0", "?"))[:8]
      except Exception:
        pass
      continue
    if w == "can":
      for m in msg.can:
        if m.src != 2:
          continue
        d = m.dat
        if m.address == 780 and len(d) >= 7:
          idx = (d[3] | (d[4] << 8)) & 0x3FF
        elif m.address == 804 and len(d) >= 7:
          v = ((d[5] | (d[6] << 8)) & 0x3FF) * 0.32
          spd = v if v < 320 else 0.0
    elif w == "carState":
      v_ego = msg.carState.vEgo
    elif w == "modelV2":
      lv = msg.modelV2.leadsV3
      vis = []
      for i in range(2):
        if i < len(lv):
          vis.append((float(lv[i].prob), float(lv[i].x[0]) - RADAR_TO_CAMERA, float(lv[i].v[0])))
        else:
          vis.append((0.0, 0.0, 0.0))
      rows.append(dict(t=msg.logMonoTime * 1e-9, idx=idx, spd=spd, v_ego=v_ego, vis=vis,
                       rec=[None, None], pres=[False, False]))
    elif w == "radarState":
      if rows:
        rs = msg.radarState
        for i, ln in enumerate(("leadOne", "leadTwo")):
          lead = getattr(rs, ln)
          rows[-1]["rec"][i] = float(lead.dRel)
          rows[-1]["pres"][i] = bool(lead.present)
  return rows, meta


def fuse_chain(rows, reseed_fix, lead_index):
  """复算 _macan_fuse_leads 的 leadOne/leadTwo 分支（含 idx 滞回/保持）。"""
  out = np.full(len(rows), np.nan)
  have = np.zeros(len(rows), dtype=bool)
  smooth, last_fused = {}, {}       # 平滑器 / 变化率基准
  last_valid_idx, hyst_t0, hyst_invalid = 0.0, 0.0, False
  for k, r in enumerate(rows):
    idx_use = r["idx"]
    if 0 < idx_use < 1021:
      last_valid_idx, hyst_invalid = idx_use, False
      have_stock = True
    elif last_valid_idx > 0:
      if not hyst_invalid:
        hyst_invalid, hyst_t0, idx_use = True, r["t"], last_valid_idx
        have_stock = True
      elif r["t"] - hyst_t0 <= HYST_WIN:
        idx_use, have_stock = last_valid_idx, True
      else:
        hyst_invalid, last_valid_idx, have_stock = False, 0.0, False
    else:
      have_stock = False
    stock = idx_to_drel(idx_use, r["v_ego"]) if have_stock else 0.0

    if not r["pres"][lead_index]:
      if reseed_fix:
        smooth.pop(0, None)
        last_fused.pop(0, None)
      have[k] = False
      continue

    prob, d_vis, v_vis = r["vis"][lead_index]
    if prob < MACAN_VISION_PROB_MIN or not (0.0 < d_vis < 150.0):
      have[k] = False        # d_vis=None -> 保留上游结果，两条分支一致
      continue

    d_used = d_vis
    gate = max(MACAN_FUSE_REL_GATE * d_vis, MACAN_FUSE_MIN_GAP)
    if 0.0 < stock < d_vis and (d_vis - stock) <= gate:
      d_used = stock

    max_step = MACAN_RATE_MIN_STEP + MACAN_RATE_VFACTOR * max(r["v_ego"], 0.0) * DT_MDL
    prev = last_fused.get(0)
    if reseed_fix and prev is not None and \
       (prev - d_used) > max(MACAN_RESEED_MIN_JUMP, MACAN_RESEED_STEP_FACTOR * max_step):
      smooth.pop(0, None)
      last_fused.pop(0, None)
      prev = None
    if 0 not in smooth:
      smooth[0] = FirstOrderFilter(d_used, MACAN_SMOOTH_RC, DT_MDL)
    d_used = smooth[0].update(d_used)
    if prev is not None:
      d_used = float(np.clip(d_used, prev - max_step, prev + max_step))
    last_fused[0] = d_used
    out[k], have[k] = d_used, True
  return out, have


def main():
  route = sys.argv[1]
  segs = sys.argv[2:] or [f"{route}--{i}" for i in range(32)]
  tot = dict(frames=0, loss=0, reacq=0, reacq_low=0, diff_frames=0, max_err=0.0, worst=None,
             ok_frames=0, over=0, under=0, low_frames=0, far_low=0, worst_under=0.0, worst_under_case=None)
  per_seg = []
  err_a = []
  for seg in segs:
    try:
      rows, meta = parse(seg)
    except Exception as e:
      print(f"  {seg}: skip ({type(e).__name__})")
      continue
    if not rows:
      continue
    rec = np.array([r["rec"][0] if r["rec"][0] is not None else np.nan for r in rows])
    pres = np.array([r["pres"][0] for r in rows])
    A, haveA = fuse_chain(rows, reseed_fix=False, lead_index=0)
    B, haveB = fuse_chain(rows, reseed_fix=True, lead_index=0)
    v = np.array([r["v_ego"] for r in rows])

    # 校验：A（旧行为）必须复现 recorded（当次实车输出）
    m = haveA & np.isfinite(rec) & pres
    if m.sum() >= 10:
      e = np.abs(A[m] - rec[m])
      err_a.append(float(np.median(e)))

    # 丢失->重捕获事件
    reacq = np.where((~pres[:-1]) & pres[1:])[0] + 1
    loss = np.where(pres[:-1] & (~pres[1:]))[0] + 1
    both = haveA & haveB
    d = np.abs(A - B)
    diff = int((d[both] > 0.5).sum())
    if both.any() and np.nanmax(d[both]) > tot["max_err"]:
      i = int(np.nanargmax(np.where(both, d, np.nan)))
      tot["max_err"] = float(d[i])
      tot["worst"] = (seg, int(i), float(v[i]), float(A[i]), float(B[i]), float(rec[i]) if np.isfinite(rec[i]) else float("nan"))
    tot["frames"] += len(rows)
    tot["loss"] += len(loss)
    tot["reacq"] += len(reacq)
    tot["reacq_low"] += int((v[reacq] < 2.0).sum()) if len(reacq) else 0
    tot["diff_frames"] += diff
    # 安全方向细分：A(旧) 相对 B(新) 报得更远 = 该刹未刹；更近 = 幽灵刹车
    low = both & (v < 3.0)
    over = both & (A > B + 1.0)          # 旧值更远 -> 少刹车风险
    under = both & (A < B - 1.0)         # 旧值更近 -> 幽灵刹车
    far = over & low
    med_err = float(np.median(np.abs(A[m] - rec[m]))) if m.sum() >= 10 else float("nan")
    if np.isfinite(med_err) and med_err < 0.4:
      tot["ok_frames"] += int(m.sum())
      tot["over"] += int(over.sum()); tot["under"] += int(under.sum())
      tot["low_frames"] += int(low.sum()); tot["far_low"] += int(far.sum())
      if far.any() and float(np.nanmax((A - B)[far])) > tot["worst_under"]:
        i = int(np.nanargmax(np.where(far, A - B, np.nan)))
        tot["worst_under"] = float((A - B)[i])
        tot["worst_under_case"] = (seg, int(i), float(v[i]), float(A[i]), float(B[i]), float(rec[i]) if np.isfinite(rec[i]) else float("nan"))
    print(f"  {seg}: {meta['commit']} {meta['branch']} fusion={meta['fusion_param']} | frames={len(rows):5d} "
          f"reacq={len(reacq):3d} A!=B>0.5m={diff:4d} 旧更远(少刹)={int(over.sum()):4d} "
          f"低速域={int(far.sum()):3d} | med|A-rec|={med_err:.3f}m")

  print("\n===== 汇总（仅统计 A 能复现 recorded 的段 = 融合确实在跑）=====")
  print(f"可用帧 {tot['ok_frames']}（其中 vEgo<3 m/s: {tot['low_frames']}）")
  print(f"旧行为比新行为报得【更远 >1 m】(少刹车风险) 的帧: {tot['over']}，其中低速域 {tot['far_low']}")
  print(f"旧行为比新行为报得【更近 >1 m】(幽灵刹车) 的帧: {tot['under']}")
  if tot["worst_under_case"]:
    s_, i_, ve_, a_, b_, rc_ = tot["worst_under_case"]
    print(f"低速域最严重少刹: {s_} frame{i_} vEgo={ve_:.2f}m/s 旧={a_:.2f}m 新={b_:.2f}m recorded={rc_:.2f}m")
  print(f"回放帧数 {tot['frames']}, lead 丢失事件 {tot['loss']}, 重捕获事件 {tot['reacq']}（其中 v<2m/s: {tot['reacq_low']}）")
  print(f"A/B 相差 >0.5 m 的帧数 {tot['diff_frames']}")
  if err_a:
    print(f"harness 自校验: A 复现 recorded dRel 的中位绝对误差 = {np.median(err_a):.4f} m")
  if tot["worst"]:
    s, i, ve, a, b, rc = tot["worst"]
    print(f"最大一次差异: {s} frame{i} vEgo={ve:.2f}m/s  旧(无复位)={a:.2f}m 新(复位)={b:.2f}m  recorded={rc:.2f}m")


if __name__ == "__main__":
  main()
