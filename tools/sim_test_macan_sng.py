#!/usr/bin/env python3
"""
Macan 起步跟停（SnGCarController）开关行为仿真验证
===================================================
验证 stop_and_go 开/关两种状态下触发逻辑是否正确，含挡位限制场景。

用法：python3 ai/tools/sim_test_macan_sng.py
"""
import sys

sys.path.insert(0, '/data/openpilot')
sys.path.insert(0, '/data/openpilot/opendbc_repo')

from opendbc.car import structs
from opendbc.sunnypilot.car.volkswagen.values_ext import VolkswagenFlagsSP
from opendbc.sunnypilot.car.volkswagen.stop_and_go import (
  SnGCarController, _RESUME_ACCEL_THRESHOLD, _RESUME_PULSE_FRAMES, _RESUME_COOLDOWN_FRAMES,
  _LEAD_MOVE_CONFIRM_FRAMES,
)
from unittest import mock

GRA_STOCK = {
  "LS_Hauptschalter": 1, "LS_Typ_Hauptschalter": 0, "LS_Codierung": 0,
  "LS_Tip_Stufe_2": 0, "COUNTER": 0, "LS_Abbrechen": 0,
  "LS_Tip_Wiederaufnahme": 0, "LS_Tip_Setzen": 0, "LS_Tip_Hoch": 0,
  "LS_Tip_Runter": 0, "CHECKSUM": 0,
}


def make_car_params():
  CP = structs.CarParams()
  CP.brand = "volkswagen"
  CP.carFingerprint = "PORSCHE_MACAN_MK1"
  CP.pcmCruise = True
  # 2026-09-07 起 stop_and_go 增加门控：仅开环纵向（openpilotLongitudinalControl）时
  # SnG 才启用（纯原厂 ACC 下 OP 不介入原厂起步）。此处必须同步，否则 enabled 恒为
  # False、全部"应代发 RESUME"用例假红（got 0）。
  CP.openpilotLongitudinalControl = True
  return CP


def make_cc(enabled=True, accel=0.5):
  CC = structs.CarControl()
  CC.enabled = enabled
  CC.actuators.accel = accel
  return CC


class Out:
  """模拟 carstate 实例的 .out（capnp CarStateOut 的 duck-type）"""
  def __init__(self, v_ego=0.0, standstill=True, gas=False, brake=False, gear_shifter=None, stock_lead_distance=0, acc05_stock_status=3):
    self.vEgo = v_ego
    self.standstill = standstill
    self.gasPressed = gas
    self.brakePressed = brake
    self.gearShifter = gear_shifter if gear_shifter is not None else structs.CarState.GearShifter.drive


class MockCS:
  """模拟 carstate 实例（carcontroller 实际收到的是 carstate 实例，不是纯 capnp）

  2026-10-07（SnG 闸门）新增字段：
  - stock_lead_object / stock_lead_speed_kph：闸门1「前车必须在动」的原厂源
    （ACC_02 ACC_Relevantes_Objekt / ACC_04 ACC_Geschw_Zielfahrzeug；327.36=无目标）。
  - op_lead_vis_dRel / op_lead_vis_vLead：闸门1/2 的**原始视觉**源
    （真实链路 controlsd_ext(modelV2 leadsV3[0]) → CC_SP.params(visLeadDist/visLeadVLead)
    → carcontroller.set_vision_lead；单测里由 sng() 转发，见下）。
  """
  def __init__(self, v_ego=0.0, standstill=True, gas=False, brake=False, gear_shifter=None,
               stock_lead_distance=0, acc05_stock_status=3, stock_lead_object=1,
               stock_lead_speed_kph=30.0, vis_dist=None, vis_vlead=0.0):
    self.out = Out(v_ego, standstill, gas, brake, gear_shifter)
    self.gra_stock_values = dict(GRA_STOCK)
    self.stock_lead_distance = stock_lead_distance  # v3: 原厂雷达Abstandsindex
    self.acc05_stock_status = acc05_stock_status  # v4: 原厂ACC_Status(3=active)
    self.stock_lead_object = stock_lead_object    # 原厂雷达是否锁到跟车目标(=1)
    self.stock_lead_speed_kph = stock_lead_speed_kph  # 原厂前车速度（327.36=无目标）
    self.op_lead_vis_dRel = vis_dist              # 视觉前车距离（米，未融合）
    self.op_lead_vis_vLead = vis_vlead            # 视觉前车速度（m/s）


def make_cs(v_ego=0.0, standstill=True, gas=False, brake=False, gear_shifter=None,
            stock_lead_distance=0, acc05_stock_status=3, stock_lead_object=1,
            stock_lead_speed_kph=30.0, vis_dist=None, vis_vlead=0.0):
  return MockCS(v_ego, standstill, gas, brake, gear_shifter, stock_lead_distance,
                acc05_stock_status, stock_lead_object, stock_lead_speed_kph, vis_dist, vis_vlead)


class FakeParams:
  """模拟 Params：get_bool/get 返回可配置 dict（测试起步距离 0/3/5/10 等状态）"""
  def __init__(self, values: dict):
    self.values = values

  def get_bool(self, key: str) -> bool:
    return self.values.get(key, False)

  def get(self, key: str, return_default: bool = False):
    v = self.values.get(key)
    if v is None:
      return None
    return v


_PRIME_FRAME = 500000   # 预热专用帧号段（远离用例帧号，避免与 idx 新鲜度语义打架）


def sng(ctrl, ccs, cc, cs, frame):
  """一帧 SnG（与 carcontroller 同路径）：先把本帧视觉源喂进控制器再判定。

  真实链路：controlsd_ext 取 modelV2.leadsV3[0] → CC_SP.params[visLeadDist/visLeadVLead]
  → carcontroller.set_vision_lead()。单测用 CS 上的 op_lead_vis_* 模拟这三个字段。
  """
  ctrl.set_vision_lead(getattr(cs, 'op_lead_vis_dRel', None), getattr(cs, 'op_lead_vis_vLead', 0.0))
  return ctrl.create_stop_and_go(ccs, None, 2, cc, cs, frame)


def prime(ctrl, ccs, n=None, accel=-0.55, **cs_kw):
  """闸门1 预热：前车在动必须连续 ≥1 s（100 帧）才允许代发 RESUME。

  预热用 accel=-0.55（低于 0.15 阈值）→ 不会真的发脉冲/进冷却；
  idx 默认 200（与用例里的 300/188/80 不同）→ 用例首帧的 idx 变化会被判为「新鲜」，
  使 idx 通道在用例期间依然可测；预热帧号段独立，不影响用例帧号语义。
  """
  global _PRIME_FRAME
  n = n if n is not None else _LEAD_MOVE_CONFIRM_FRAMES + 20
  for i in range(n):
    kw = dict(cs_kw)
    kw.setdefault('standstill', True)
    kw.setdefault('stock_lead_distance', 200)
    sng(ctrl, ccs, make_cc(enabled=True, accel=accel), make_cs(**kw), _PRIME_FRAME + i)
  _PRIME_FRAME += n + 10


def make_ctrl(CP=None, CP_SP=None, params_dict: dict | None = None):
  """隔离真实 Params（设备上 MacanStartStop 真实值会污染 enabled 判定）：
  - params_dict=None：让 Params() 抛异常 → _mp=None → 距离开关取默认(True)
  - params_dict=dict：提供 FakeParams（测试 SnG/距离开关 开/关状态）"""
  import openpilot.common.params as params_mod
  if params_dict is None:
    with mock.patch.object(params_mod, "Params", side_effect=Exception("test isolation")):
      return SnGCarController(CP if CP is not None else make_car_params(),
                              CP_SP if CP_SP is not None else structs.CarParamsSP())
  with mock.patch.object(params_mod, "Params", return_value=FakeParams(params_dict)):
    return SnGCarController(CP if CP is not None else make_car_params(),
                            CP_SP if CP_SP is not None else structs.CarParamsSP())


class FakeCCS:
  """模拟 mlbcan.create_acc_buttons_control"""
  def create_acc_buttons_control(self, packer, bus, gra_stock_values, cancel=False, resume=False,
                                 set_increase=False, set_decrease=False):
    return ("LS_01", bus, {"resume": resume, "cancel": cancel, "set": set_increase}, 0)


PASS = 0
FAIL = 0


def check(name, cond, detail=""):
  global PASS, FAIL
  if cond:
    PASS += 1
    print(f"  ✅ {name}")
  else:
    FAIL += 1
    print(f"  ❌ {name}  {detail}")


def run():
  global PASS, FAIL
  print("=" * 70)
  print("Macan 起步跟停（SnGCarController）开关行为仿真")
  print("=" * 70)

  # ---------- 场景组1：开关关闭（MacanStartStop=0，默认） ----------
  print("\n【场景组1】开关关闭（flags=0）—— 应保持原厂行为，绝不代发")
  ctrl_off = make_ctrl()
  ccs = FakeCCS()
  check("关：enabled 标志位为 False", ctrl_off.enabled is False, f"got {ctrl_off.enabled}")

  sends = sng(ctrl_off, ccs, make_cc(enabled=True, accel=0.5), make_cs(standstill=True, stock_lead_distance=300), 100)
  check("关：standstill+accel>0.15 不代发 RESUME", len(sends) == 0, f"got {len(sends)}")

  sends = sng(ctrl_off, ccs, make_cc(enabled=False, accel=0.5), make_cs(standstill=True, stock_lead_distance=300), 100)
  check("关：enabled=False 也不代发", len(sends) == 0)

  # ---------- 场景组2：开关开启（MacanStartStop=1） ----------
  print("\n【场景组2】开关开启（flags=STOP_AND_GO）—— 正常触发")
  CP_SP = structs.CarParamsSP()
  CP_SP.flags = VolkswagenFlagsSP.STOP_AND_GO
  ctrl_on = make_ctrl(CP_SP=CP_SP)
  check("开：enabled 标志位已设置", ctrl_on.enabled is True)

  # 2.1 正常触发：连续5帧 enabled + standstill + accel>0.15 + 无干预 → 代发 RESUME
  prime(ctrl_on, ccs, stock_lead_distance=300, vis_dist=13.0)   # 闸门1 预热：前车在动需连续 ≥1s
  sends = []
  for f in range(200, 205):
    sends = sng(ctrl_on, ccs, make_cc(enabled=True, accel=0.5), make_cs(standstill=True, stock_lead_distance=300), f)
  check("开：连续5帧起步条件满足 → 代发 RESUME 1帧", len(sends) == 1, f"got {len(sends)}")
  if sends:
    addr, bus, vals, _ = sends[0]
    check("开：帧地址 LS_01、bus=2(ext=ACC侧)", addr == "LS_01" and bus == 2, f"addr={addr} bus={bus}")
    check("开：resume 信号置位", vals["resume"] is True)

  # 2.2 OP 未启用 → 不代发
  sends = sng(ctrl_on, ccs, make_cc(enabled=False, accel=0.5), make_cs(standstill=True, stock_lead_distance=300), 205)
  check("开：CC.enabled=False 不代发", len(sends) == 0)

  # 2.3 模型未放行（accel<=0.15）→ 不代发
  prime(ctrl_on, ccs, stock_lead_distance=300, vis_dist=13.0)   # 闸门1 预热：前车在动需连续 ≥1s
  sends = sng(ctrl_on, ccs, make_cc(enabled=True, accel=0.1), make_cs(standstill=True, stock_lead_distance=300), 206)
  check("开：accel=0.1(≤0.15) 不代发（红灯/前车未动）", len(sends) == 0, f"got {len(sends)}")

  # 2.4 行驶中（非standstill）→ 不代发
  sends = sng(ctrl_on, ccs, make_cc(enabled=True, accel=0.5), make_cs(v_ego=5.0, standstill=False, stock_lead_distance=300), 207)
  check("开：行驶中(vEgo=5)不代发", len(sends) == 0)

  # 2.5 驾驶员踩油门/刹车 → 不代发（安全兜底）
  sends = sng(ctrl_on, ccs, make_cc(enabled=True, accel=0.5), make_cs(standstill=True, gas=True, stock_lead_distance=300), 208)
  check("开：踩油门时绝不代发（驾驶员优先）", len(sends) == 0, f"got {len(sends)}")
  sends = sng(ctrl_on, ccs, make_cc(enabled=True, accel=0.5), make_cs(standstill=True, brake=True, stock_lead_distance=300), 209)
  check("开：踩刹车时绝不代发", len(sends) == 0)

  # 2.6 防抖：脉冲锁定（180ms 单脉冲）——中间 aTarget 抖动不中断
  print(f"\n【场景组2b】防抖验证：锁定 {_RESUME_PULSE_FRAMES*10}ms 单脉冲，aTarget 抖动不中断")
  ctrl_loop = make_ctrl(CP_SP=CP_SP)
  prime(ctrl_loop, ccs, stock_lead_distance=300, vis_dist=13.0)   # 闸门1 预热：前车在动需连续 ≥1s
  sent_seq = []
  sent = 0
  for frame in range(0, 60):
    # 注入抖动：第 10-15 帧 aTarget 掉到 0.1（<0.15）——旧实现会中断脉冲成簇（毛刺根因）
    accel = 0.1 if 10 <= frame <= 15 else 0.5
    sends = sng(ctrl_loop, ccs, make_cc(enabled=True, accel=accel),
                                         make_cs(standstill=True, stock_lead_distance=300), frame)
    sent += len(sends)
    sent_seq.append(1 if sends else 0)
  check(f"防抖：60帧共发送 {sent} 帧（应为单脉冲 {_RESUME_PULSE_FRAMES} 帧，抖动不中断）",
        sent == _RESUME_PULSE_FRAMES, f"got {sent}")
  # 序列：f0-3 确认(False) → f4-21 脉冲(True×18) → f22-59 冷却(False)；抖动帧(10-15)在脉冲内不中断
  expected = [0]*4 + [1]*_RESUME_PULSE_FRAMES + [0]*(60-4-_RESUME_PULSE_FRAMES)
  check("脉冲连续性：4帧确认→连续18帧→冷却停止（抖动帧不中断）", sent_seq == expected, f"got {sent_seq}")

  # 2.7 车动起来后重置 → 可再次触发（需重新5帧确认）
  print("\n【场景组2c】重置验证：车动起来后可再次触发")
  ctrl_reset = make_ctrl(CP_SP=CP_SP)
  prime(ctrl_reset, ccs, stock_lead_distance=300, vis_dist=13.0)   # 闸门1 预热：前车在动需连续 ≥1s
  for f in range(1, 6):
    sng(ctrl_reset, ccs, make_cc(enabled=True, accel=0.5), make_cs(standstill=True, stock_lead_distance=300), f)
  sng(ctrl_reset, ccs, make_cc(enabled=True, accel=0.5), make_cs(v_ego=2.0, standstill=False, stock_lead_distance=300), 6)
  sends = []
  for f in range(7, 12):
    sends = sng(ctrl_reset, ccs, make_cc(enabled=True, accel=0.5), make_cs(standstill=True, stock_lead_distance=300), f)
  check("重置：行驶后再次停车可再次触发", len(sends) == 1, f"got {len(sends)}")

  # 2.7b 冷却：脉冲后车未动 → 3s 冷却内不重发；车动(vEgo>0.5) → 立即解除
  print("\n【场景组2c-2】冷却验证：脉冲后不立即重发，车动立即解除")
  ctrl_cd = make_ctrl(CP_SP=CP_SP)
  prime(ctrl_cd, ccs, stock_lead_distance=300, vis_dist=13.0)   # 闸门1 预热：前车在动需连续 ≥1s
  for f in range(1, 24):  # 4帧确认 + 18帧脉冲（f5触发，f6-22脉冲，f22末设冷却）
    sng(ctrl_cd, ccs, make_cc(enabled=True, accel=0.5),
                               make_cs(standstill=True, stock_lead_distance=300), f)
  sends = sng(ctrl_cd, ccs, make_cc(enabled=True, accel=0.5),
                                     make_cs(standstill=True, stock_lead_distance=300), 25)
  check("冷却：脉冲结束后条件仍满足但不立即重发", len(sends) == 0, f"got {len(sends)}")
  sng(ctrl_cd, ccs, make_cc(enabled=True, accel=0.5),
                             make_cs(v_ego=2.0, standstill=False, stock_lead_distance=300), 26)
  sends = []
  for f in range(27, 32):
    sends = sng(ctrl_cd, ccs, make_cc(enabled=True, accel=0.5),
                                       make_cs(standstill=True, stock_lead_distance=300), f)
  check("冷却解除：车动后再次停车可重新触发", len(sends) == 1, f"got {len(sends)}")

  # 2.8 挡位限制：非前进挡（P/R/N）不代发，前进挡（D/S/M）正常
  print("\n【场景组2e】挡位限制：非前进挡不代发 RESUME")
  GS = structs.CarState.GearShifter
  for name, gear, expect_send in (
      ("P挡（park）", GS.park, 0),
      ("R挡（reverse）", GS.reverse, 0),
      ("N挡（neutral）", GS.neutral, 0),
      ("未知挡（unknown）", GS.unknown, 0),
      ("D挡（drive）", GS.drive, 1),
      ("S挡（sport）", GS.sport, 1),
      ("M挡（manumatic）", GS.manumatic, 1),
  ):
    ctrl_g = make_ctrl(CP_SP=CP_SP)
    prime(ctrl_g, ccs, stock_lead_distance=300, vis_dist=13.0)   # 闸门1 预热
    sends = []
    for f in range(1000, 1005):
      sends = sng(ctrl_g, ccs, make_cc(enabled=True, accel=0.5),
                                        make_cs(standstill=True, gear_shifter=gear, stock_lead_distance=300), f)
    ok = len(sends) == expect_send
    check(f"{name}：{'代发' if expect_send else '不代发'} RESUME", ok, f"got {len(sends)}")

  # 2.9 挡位限制下的防抖重置：P挡判定后回D挡应可再次触发
  ctrl_pd = make_ctrl(CP_SP=CP_SP)
  prime(ctrl_pd, ccs, stock_lead_distance=300, vis_dist=13.0)   # 闸门1 预热：前车在动需连续 ≥1s
  sends = []
  for f in range(1100, 1105):
    sends = sng(ctrl_pd, ccs, make_cc(enabled=True, accel=0.5),
                                       make_cs(standstill=True, gear_shifter=GS.park, stock_lead_distance=300), f)
  check("P挡：5帧不代发且计数清零", len(sends) == 0)
  sends = []
  for f in range(1105, 1110):
    sends = sng(ctrl_pd, ccs, make_cc(enabled=True, accel=0.5),
                                       make_cs(standstill=True, gear_shifter=GS.drive, stock_lead_distance=300), f)
  check("P挡后回D挡：5帧确认后触发", len(sends) == 1, f"got {len(sends)}")

  # 2.11 v3新增：起步需原厂雷达ab>0（前车被雷达捕捉），视觉不代发起步
  # 2026-10-07：取消 0=Off 语义；默认 6 米，范围 3~10 米（均为前保险杠→前车距离）
  print("\n【场景组2f】起步安全距离（MacanStartStopDistance 米：3~10，默认 6；Off 已取消）")
  # 默认 6 米：ab=0 无视觉 → 不代发（0m < 6m）；ab=300 → 代发（300*0.0424=12.7m > 6m）
  ctrl_d6 = make_ctrl(CP_SP=CP_SP)
  prime(ctrl_d6, ccs, stock_lead_distance=300, vis_dist=13.0)   # 闸门1 预热：前车在动需连续 ≥1s
  check("默认6米：enabled=True", ctrl_d6.enabled is True)
  check("默认6米：_distance_m==6.0", ctrl_d6._distance_m == 6.0, f"got {ctrl_d6._distance_m}")
  sends = []
  for f in range(2000, 2005):
    sends = sng(ctrl_d6, ccs, make_cc(enabled=True, accel=0.5),
                                       make_cs(standstill=True, stock_lead_distance=0), f)
  check("6米：ab=0无视觉(0m<6m) → 不代发", len(sends) == 0, f"got {len(sends)}")
  sends = []
  for f in range(2010, 2015):
    sends = sng(ctrl_d6, ccs, make_cc(enabled=True, accel=0.5),
                                       make_cs(standstill=True, stock_lead_distance=300), f)
  check("6米：ab=300(12.7m>6m) → 代发", len(sends) == 1, f"got {len(sends)}")
  # 3 米：ab=70(2.97m<3m) 不代发；ab=80(3.4m>3m) 代发
  ctrl_d3 = make_ctrl(CP_SP=CP_SP, params_dict={"MacanStartStop": True, "MacanStartStopDistance": "3"})
  prime(ctrl_d3, ccs, stock_lead_distance=300, vis_dist=13.0)   # 闸门1 预热：前车在动需连续 ≥1s
  sends = []
  for f in range(2020, 2025):
    sends = sng(ctrl_d3, ccs, make_cc(enabled=True, accel=0.5),
                                       make_cs(standstill=True, stock_lead_distance=70), f)
  check("3米：ab=70(2.97m<3m) → 不代发", len(sends) == 0, f"got {len(sends)}")
  sends = []
  for f in range(2030, 2035):
    sends = sng(ctrl_d3, ccs, make_cc(enabled=True, accel=0.5),
                                       make_cs(standstill=True, stock_lead_distance=80), f)
  check("3米：ab=80(3.4m>3m) → 代发", len(sends) == 1, f"got {len(sends)}")
  # 2026-10-07：0=Off 已取消 —— 0/非法读数一律回退默认 6 米（不再有"纯意图起步"路径）
  ctrl_d0 = make_ctrl(CP_SP=CP_SP, params_dict={"MacanStartStop": True, "MacanStartStopDistance": "0"})
  prime(ctrl_d0, ccs, stock_lead_distance=300, vis_dist=13.0)   # 闸门1 预热：前车在动需连续 ≥1s
  check("0(旧Off)：enabled=True（SnG开）", ctrl_d0.enabled is True)
  check("0(旧Off)：回退默认 6 米", ctrl_d0._distance_m == 6.0, f"got {ctrl_d0._distance_m}")
  sends = []
  for f in range(2040, 2045):
    sends = sng(ctrl_d0, ccs, make_cc(enabled=True, accel=0.5),
                                       make_cs(standstill=True, stock_lead_distance=0), f)
  check("0(旧Off)：ab=0无视觉 → 不代发（无纯意图起步）", len(sends) == 0, f"got {len(sends)}")
  # 无效/越界读数（99）同样回退默认 6 米
  ctrl_dbad = make_ctrl(CP_SP=CP_SP, params_dict={"MacanStartStop": True, "MacanStartStopDistance": "99"})
  check("越界(99)：回退默认 6 米", ctrl_dbad._distance_m == 6.0, f"got {ctrl_dbad._distance_m}")

  # 2.12 v4新增：原厂ACC必须active（bus2 ACC_05 st=3）才代发RESUME——刚上车/未激活不代发
  print("\n【场景组2g】v4原厂ACC激活确认：st==3才代发")
  ctrl_v4 = make_ctrl(CP_SP=CP_SP)
  prime(ctrl_v4, ccs, stock_lead_distance=300, vis_dist=13.0)   # 闸门1 预热：前车在动需连续 ≥1s
  sends = []
  for f in range(2100, 2105):
    sends = sng(ctrl_v4, ccs, make_cc(enabled=True, accel=0.5),
                                       make_cs(standstill=True, stock_lead_distance=300, acc05_stock_status=2), f)
  check("v4：原厂st=2(ACC未激活/刚上车) 不代发RESUME", len(sends) == 0, f"got {len(sends)}")
  ctrl_v4b = make_ctrl(CP_SP=CP_SP)
  prime(ctrl_v4b, ccs, stock_lead_distance=300, vis_dist=13.0)   # 闸门1 预热：前车在动需连续 ≥1s
  sends = []
  for f in range(2110, 2115):
    sends = sng(ctrl_v4b, ccs, make_cc(enabled=True, accel=0.5),
                                        make_cs(standstill=True, stock_lead_distance=300, acc05_stock_status=3), f)
  check("v4：原厂st=3(ACC active停车保持) → 代发RESUME", len(sends) == 1, f"got {len(sends)}")

  # 2.14 v6新增（2026-10-07）：SnG 起步闸门回归 —— route 00000091 seg9 误起步场景
  # 实测触发链：原厂 idx 冻结在 188（×0.0424=7.97 m，"看起来有效"）+ 本车蠕行靠近前车
  # （视觉 6.09→3.69 m）+ 前车静止 → 旧实现仍代发 LS_01 RESUME（T=673.5）→ 12 ms 后原厂
  # loes=1/anh 1→0 放行 → 误起步 → T=683.5 st=6 退出纵向。
  print("\n【场景组2h】SnG 起步闸门回归（seg9 误起步 / idx 冻结 / 前车静止）")

  # 2h-A 前车静止（原厂前车速度=0、视觉 vLead=0）+ idx 冻结 188 + 视觉 6.09m
  #      → 闸门1 拦截：前车没动 → 0 次代发（旧实现会代发 1 次）
  ctrl_s9 = make_ctrl(CP_SP=CP_SP)
  total = 0
  for f in range(3000, 3200):     # 2 s，足以越过脉冲/冷却窗口
    total += len(sng(ctrl_s9, ccs, make_cc(enabled=True, accel=0.5),
                     make_cs(standstill=True, stock_lead_distance=188, stock_lead_object=1,
                             stock_lead_speed_kph=0.0, vis_dist=6.09, vis_vlead=0.0), f))
  check("seg9：前车静止(idx冻结188 / 视觉6.09m / 视觉vLead=0) → 0 次代发", total == 0, f"got {total}")

  # 2h-B 前车确实动了（原厂 5 km/h）但只持续 0.5 s（50 帧）→ 闸门1 拦截
  ctrl_s9b = make_ctrl(CP_SP=CP_SP)
  total = 0
  for f in range(3300, 3350):
    total += len(sng(ctrl_s9b, ccs, make_cc(enabled=True, accel=0.5),
                     make_cs(standstill=True, stock_lead_distance=300, stock_lead_speed_kph=5.0,
                             vis_dist=12.0, vis_vlead=1.4), f))
  check("闸门1：前车在动仅 0.5 s（<1 s）→ 0 次代发", total == 0, f"got {total}")
  # 2h-C 同一辆车继续 → 累计 ≥1 s 后才放行
  total = 0
  for f in range(3350, 3430):
    total += len(sng(ctrl_s9b, ccs, make_cc(enabled=True, accel=0.5),
                     make_cs(standstill=True, stock_lead_distance=300, stock_lead_speed_kph=5.0,
                             vis_dist=12.0, vis_vlead=1.4), f))
  check("闸门1：前车在动累计 ≥1 s → 代发 RESUME", total >= 1, f"got {total}")

  # 2h-D 闸门2：前车在动(已预热) 但视觉只有 3.69 m（刚跟停贴太近）→ 不代发
  ctrl_s9c = make_ctrl(CP_SP=CP_SP)
  prime(ctrl_s9c, ccs, stock_lead_distance=300, stock_lead_speed_kph=5.0, vis_dist=3.69, vis_vlead=1.4)
  total = 0
  for f in range(3500, 3510):
    total += len(sng(ctrl_s9c, ccs, make_cc(enabled=True, accel=0.5),
                     make_cs(standstill=True, stock_lead_distance=300, stock_lead_speed_kph=5.0,
                             vis_dist=3.69, vis_vlead=1.4), f))
  check("闸门2：视觉 3.69 m < 6 m 门 → 0 次代发", total == 0, f"got {total}")

  # 2h-E 冻结 idx 不参与距离门：视觉 12 m + idx 冻结 188（7.97 m）→ 靠视觉过门 → 代发
  ctrl_s9d = make_ctrl(CP_SP=CP_SP)
  prime(ctrl_s9d, ccs, stock_lead_distance=188, stock_lead_speed_kph=5.0, vis_dist=12.0, vis_vlead=1.4)
  total = 0
  for f in range(3550, 3560):
    total += len(sng(ctrl_s9d, ccs, make_cc(enabled=True, accel=0.5),
                     make_cs(standstill=True, stock_lead_distance=188, stock_lead_speed_kph=5.0,
                             vis_dist=12.0, vis_vlead=1.4), f))
  check("闸门2：idx 冻结(188)被排除、视觉 12 m 过门 → 代发（前车在动）", total >= 1, f"got {total}")

  # 2h-F 视觉漏检时雷达兜底：无视觉 + idx 每帧变化（新鲜，低速域也有效）且 >6 m → 代发
  ctrl_s9e = make_ctrl(CP_SP=CP_SP)
  prime(ctrl_s9e, ccs, stock_lead_distance=300, stock_lead_speed_kph=5.0)
  total = 0
  for f in range(3600, 3606):
    total += len(sng(ctrl_s9e, ccs, make_cc(enabled=True, accel=0.5),
                     make_cs(standstill=True, stock_lead_distance=280 + (f % 5),
                             stock_lead_speed_kph=5.0, vis_dist=None), f))
  check("闸门2：无视觉但 idx 新鲜(逐帧变化)且 >6 m → 代发（雷达兜底）", total >= 1, f"got {total}")

  # 2h-G 冷启动/无目标保护：前后都没有有效距离源 → 0 次代发
  ctrl_s9f = make_ctrl(CP_SP=CP_SP)
  prime(ctrl_s9f, ccs, stock_lead_distance=0, stock_lead_speed_kph=5.0)
  total = 0
  for f in range(3650, 3660):
    total += len(sng(ctrl_s9f, ccs, make_cc(enabled=True, accel=0.5),
                     make_cs(standstill=True, stock_lead_distance=0,
                             stock_lead_speed_kph=5.0, vis_dist=None), f))
  check("闸门2：无视觉且 idx=0(无目标) → 0 次代发", total == 0, f"got {total}")

  # 2.13 方案B：介入镜像（st镜像 + mom/verz/axG/fv/FM/anh透传）——mlbcan 纯函数测试
  print("\n【场景组3】方案B介入镜像：st镜像+mom/verz/axG/fv/FM/anh透传")
  from opendbc.car.volkswagen.mlbcan import acc_control_value as acv, create_acc_accel_control as ccacc
  class FakePacker:
    def make_can_msg(self, name, bus, values):
      return (name, bus, values, 0)
  fp = FakePacker()
  check("st镜像：原厂3+gas→3（不自己切4）", acv(True, False, True, True, 3) == 3, f"got {acv(True, False, True, True, 3)}")
  check("st镜像：原厂4+gas→4", acv(True, False, True, True, 4) == 4, f"got {acv(True, False, True, True, 4)}")
  check("st镜像：原厂3+无gas→3", acv(True, False, True, False, 3) == 3)
  check("st镜像：兜底（stock_st=None）+gas→4", acv(True, False, True, True) == 4)
  check("st镜像：原厂6（故障/退出）→OP 2跟随（不留3/4矛盾窗口）", acv(True, False, True, False, 6) == 2, f"got {acv(True, False, True, False, 6)}")
  check("st镜像：原厂6+gas→OP 2（不兜底4）", acv(True, False, True, True, 6) == 2, f"got {acv(True, False, True, True, 6)}")
  r = ccacc(fp, 0, 'acc', True, 0.0, 3, False, False, False, v_ego=10,
            stock_follow=False, gas_override=True, stock_fv=False, stock_mom=0.0,
            stock_verz=0.0, verz_follow=False, axg_comp=False, stock_axg=-1.0,
            stock_fm=False, stock_anhalten=False)
  vals = r[0][2]
  check("mom透传：gas+stock_mom=0→mom==0（非巡航基线）", vals["ACC_Momentenanforderung"] == 0, f"got {vals['ACC_Momentenanforderung']}")
  check("axG透传：stock_axg=-1.0→axG==-1.0", abs(vals["ACC_ax_Getriebe"] - (-1.0)) < 0.001, f"got {vals['ACC_ax_Getriebe']}")
  check("verz透传：stock_verz=0→verz==0", abs(vals["ACC_Verz_anf"]) < 0.001, f"got {vals['ACC_Verz_anf']}")
  check("fv透传：stock_fv=False→fv=0", vals["ACC_Freigabe_Verzanf"] == 0, f"got {vals['ACC_Freigabe_Verzanf']}")
  check("FM透传：stock_fm=False→FM=0", vals["ACC_Freigabe_Momentenanf"] == 0, f"got {vals['ACC_Freigabe_Momentenanf']}")
  check("anh透传：stock_anhalten=False→anh=0", vals["ACC_Anhalten"] == 0, f"got {vals['ACC_Anhalten']}")
  r2 = ccacc(fp, 0, 'acc', True, 0.5, 3, False, False, False, v_ego=10,
             stock_follow=False, gas_override=False, stock_fv=True, stock_mom=100.0,
             stock_verz=0.0, verz_follow=False, axg_comp=False, stock_axg=0.0,
             stock_fm=True, stock_anhalten=True)
  vals2 = r2[0][2]
  check("非介入：mom按OP计算（>0）", vals2["ACC_Momentenanforderung"] > 0, f"got {vals2['ACC_Momentenanforderung']}")
  check("非介入：anh按OP（stopping=False→0）", vals2["ACC_Anhalten"] == 0, f"got {vals2['ACC_Anhalten']}")

  # 2.10 非 Macan（其他VW）即使开关开也不触发
  print("\n【场景组2d】平台过滤：仅 Macan(MLB) 生效")
  CP = make_car_params()
  CP.carFingerprint = "VOLKSWAGEN_GOLF_MK7"
  ctrl_other = make_ctrl(CP=CP, CP_SP=CP_SP)
  check("其他VW平台：enabled=False（不触发）", ctrl_other.enabled is False)

  print("\n" + "=" * 70)
  print(f"结果：{PASS} 通过 / {FAIL} 失败")
  if FAIL:
    print("❌ 存在失败项，请检查实现！")
    sys.exit(1)
  print("🎉 SnG 开关行为全部正确（开/关两种状态均符合预期）")
  print("=" * 70)


if __name__ == "__main__":
  run()
