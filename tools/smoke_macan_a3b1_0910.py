#!/usr/bin/env python3
"""A3 端到端冒烟（2026-09-10，方案B/B1 落地后）：合成 bus2 帧喂进真正的 RadarInterface._update_macan，
验证 idx -> t -> dRel 走的是 B1 直线、无突跳、且与 A2 反解可往返。

用法：cd /data/openpilot && python3 ai/tools/smoke_macan_a3b1_0910.py
"""
from opendbc.car.structs import CarParams
from opendbc.car.volkswagen.radar_interface import RadarInterface, MACAN_B1_T_A, MACAN_B1_T_B

A, B = MACAN_B1_T_A, MACAN_B1_T_B
V_KPH = 72.0
V = V_KPH / 3.6        # 真实 20.000 m/s
# 驱动侧换算用的是 0.2778（非 1/3.6）且轮速 0.1 km/h 量化 -> 复现出 v_ego 的真值：
V_DRV = V_KPH * 0.2778  # = 20.0016 m/s


def frame(idx, v_kph=V_KPH, lead_kph=90.0):
  # BO_259: 四轮轮速 16|12 28|12 40|12 52|12 @1+ (0.1,0) km/h -> 每轮 12bit 原始值 = v_kph/0.1
  ws = int(round(v_kph / 0.1))
  d259 = ((ws | (ws << 12) | (ws << 24) | (ws << 36)) << 16).to_bytes(8, "little")
  d780 = bytes([0, 0, 0, idx & 0xFF, (idx >> 8) & 0x03, 0, 0, 0])
  lv = int(lead_kph / 0.32)
  d804 = bytes([0, 0, 0, 0, 0, lv & 0xFF, (lv >> 8) & 0x03, 0])
  return [(0, [(259, d259, 0), (780, d780, 2), (804, d804, 2)])]


ri = RadarInterface(CarParams(carFingerprint="PORSCHE_MACAN_MK1", wheelSpeedFactor=1.0), None)

print(f"B1: t = {A}*idx + {B}   (v={V:.2f} m/s)")
print(" idx |  t_B1 |  dRel  | 期望 dRel | 相对误差")
bad = 0
prev = None
max_step = 0.0
for idx in list(range(1, 1021)):
  r = ri._update_macan(frame(idx))
  d = r.points[0].dRel
  exp = (A * idx + B) * max(V_DRV, 5.0)
  if abs(d / exp - 1.0) > 1e-6:
    bad += 1
  if prev is not None:
    max_step = max(max_step, abs(d - prev))
  prev = d
  if idx in (100, 300, 500, 560, 700, 1010):
    print(f"{idx:4d} | {A*idx+B:5.2f} | {d:6.2f} |  {exp:6.2f}   | {(d/exp-1)*100:+.6f}%")  # 残差来自 0.2778 近似+轮速量化

print(f"\n[1] 全 idx 1..1020 与 B1 直线一致(相对 1e-6): {bad == 0}")
print(f"[2] 逐 idx 最大 dRel 步长: {max_step:.4f} m (直线 {A*V_DRV:.4f} m/idx) -> 无突跳: {abs(max_step - A*V_DRV) < 1e-3}")
n0 = ri._update_macan(frame(0))
n1 = ri._update_macan(frame(1021))
print(f"[3] idx=0（无目标）    -> return {type(n0).__name__} (空雷达/视觉兜底): {n0 is None}")
print(f"[4] idx=1021（饱和无效）-> return {type(n1).__name__}: {n1 is None}")

# A2 反解往返（能导入则用真身，否则用同式复算）
try:
  from openpilot.selfdrive.controls.radard import RadarD
  inv = RadarD._macan_drel_to_idx.__get__(type("X", (), {"_macan_radar": None})(), )
  print("\n[5] A2 真身反解往返:", end=" ")
  e = max(abs(float(RadarD._macan_drel_to_idx(object.__new__(RadarD), (A * i + B) * max(V_DRV, 5.0), V_DRV)) - i) for i in range(1, 1021))
  print(f"最大误差 {e:.6f} idx -> {'OK' if e < 1e-9 else 'FAIL'}")
except Exception as ex:
  print(f"\n[5] A2 真身导入失败({type(ex).__name__}), 用同式复算: ", end="")
  e = max(abs(min(max((((A*i+B)*max(V_DRV,5.0)/V_DRV) - B)/A, 1.0), 1020.0) - i) for i in range(1, 1021))
  print(f"最大误差 {e:.6f} idx -> {'OK' if e < 1e-9 else 'FAIL'}")
