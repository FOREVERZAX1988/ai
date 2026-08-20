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
from opendbc.sunnypilot.car.volkswagen.stop_and_go import SnGCarController, _RESUME_ACCEL_THRESHOLD, _RESUME_MAX_FRAMES
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
  return CP


def make_cc(enabled=True, accel=0.5):
  CC = structs.CarControl()
  CC.enabled = enabled
  CC.actuators.accel = accel
  return CC


class Out:
  """模拟 carstate 实例的 .out（capnp CarStateOut 的 duck-type）"""
  def __init__(self, v_ego=0.0, standstill=True, gas=False, brake=False, gear_shifter=None):
    self.vEgo = v_ego
    self.standstill = standstill
    self.gasPressed = gas
    self.brakePressed = brake
    self.gearShifter = gear_shifter if gear_shifter is not None else structs.CarState.GearShifter.drive


class MockCS:
  """模拟 carstate 实例（carcontroller 实际收到的是 carstate 实例，不是纯 capnp）"""
  def __init__(self, v_ego=0.0, standstill=True, gas=False, brake=False, gear_shifter=None):
    self.out = Out(v_ego, standstill, gas, brake, gear_shifter)
    self.gra_stock_values = dict(GRA_STOCK)


def make_cs(v_ego=0.0, standstill=True, gas=False, brake=False, gear_shifter=None):
  return MockCS(v_ego, standstill, gas, brake, gear_shifter)


def make_ctrl(CP=None, CP_SP=None):
  """隔离真实 Params（设备上 MacanStartStop 真实值会污染 enabled 判定）：
  让 init 内 Params() 抛异常 → enabled 保持 flags 判定（对应测试环境无 Params 可达）。"""
  import openpilot.common.params as params_mod
  with mock.patch.object(params_mod, "Params", side_effect=Exception("test isolation")):
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

  sends = ctrl_off.create_stop_and_go(ccs, None, 2, make_cc(enabled=True, accel=0.5), make_cs(standstill=True), 100)
  check("关：standstill+accel>0.15 不代发 RESUME", len(sends) == 0, f"got {len(sends)}")

  sends = ctrl_off.create_stop_and_go(ccs, None, 2, make_cc(enabled=False, accel=0.5), make_cs(standstill=True), 100)
  check("关：enabled=False 也不代发", len(sends) == 0)

  # ---------- 场景组2：开关开启（MacanStartStop=1） ----------
  print("\n【场景组2】开关开启（flags=STOP_AND_GO）—— 正常触发")
  CP_SP = structs.CarParamsSP()
  CP_SP.flags = VolkswagenFlagsSP.STOP_AND_GO
  ctrl_on = make_ctrl(CP_SP=CP_SP)
  check("开：enabled 标志位已设置", ctrl_on.enabled is True)

  # 2.1 正常触发：连续5帧 enabled + standstill + accel>0.15 + 无干预 → 代发 RESUME
  sends = []
  for f in range(200, 205):
    sends = ctrl_on.create_stop_and_go(ccs, None, 2, make_cc(enabled=True, accel=0.5), make_cs(standstill=True), f)
  check("开：连续5帧起步条件满足 → 代发 RESUME 1帧", len(sends) == 1, f"got {len(sends)}")
  if sends:
    addr, bus, vals, _ = sends[0]
    check("开：帧地址 LS_01、bus=2(ext=ACC侧)", addr == "LS_01" and bus == 2, f"addr={addr} bus={bus}")
    check("开：resume 信号置位", vals["resume"] is True)

  # 2.2 OP 未启用 → 不代发
  sends = ctrl_on.create_stop_and_go(ccs, None, 2, make_cc(enabled=False, accel=0.5), make_cs(standstill=True), 205)
  check("开：CC.enabled=False 不代发", len(sends) == 0)

  # 2.3 模型未放行（accel<=0.15）→ 不代发
  sends = ctrl_on.create_stop_and_go(ccs, None, 2, make_cc(enabled=True, accel=0.1), make_cs(standstill=True), 206)
  check("开：accel=0.1(≤0.15) 不代发（红灯/前车未动）", len(sends) == 0, f"got {len(sends)}")

  # 2.4 行驶中（非standstill）→ 不代发
  sends = ctrl_on.create_stop_and_go(ccs, None, 2, make_cc(enabled=True, accel=0.5), make_cs(v_ego=5.0, standstill=False), 207)
  check("开：行驶中(vEgo=5)不代发", len(sends) == 0)

  # 2.5 驾驶员踩油门/刹车 → 不代发（安全兜底）
  sends = ctrl_on.create_stop_and_go(ccs, None, 2, make_cc(enabled=True, accel=0.5), make_cs(standstill=True, gas=True), 208)
  check("开：踩油门时绝不代发（驾驶员优先）", len(sends) == 0, f"got {len(sends)}")
  sends = ctrl_on.create_stop_and_go(ccs, None, 2, make_cc(enabled=True, accel=0.5), make_cs(standstill=True, brake=True), 209)
  check("开：踩刹车时绝不代发", len(sends) == 0)

  # 2.6 防抖：连续发送上限（0.2s @100Hz = 20帧），超限后停止
  print("\n【场景组2b】防抖验证：连续发送 ≤20 帧后停止")
  ctrl_loop = make_ctrl(CP_SP=CP_SP)
  sent = 0
  for frame in range(0, 60):
    sends = ctrl_loop.create_stop_and_go(ccs, None, 2, make_cc(enabled=True, accel=0.5), make_cs(standstill=True), frame)
    sent += len(sends)
  check(f"防抖：60帧内共发送 {sent} 帧（上限应为 {_RESUME_MAX_FRAMES}）", sent == _RESUME_MAX_FRAMES, f"got {sent}")

  # 2.7 车动起来后重置 → 可再次触发（需重新5帧确认）
  print("\n【场景组2c】重置验证：车动起来后可再次触发")
  ctrl_reset = make_ctrl(CP_SP=CP_SP)
  for f in range(1, 6):
    ctrl_reset.create_stop_and_go(ccs, None, 2, make_cc(enabled=True, accel=0.5), make_cs(standstill=True), f)
  ctrl_reset.create_stop_and_go(ccs, None, 2, make_cc(enabled=True, accel=0.5), make_cs(v_ego=2.0, standstill=False), 6)
  sends = []
  for f in range(7, 12):
    sends = ctrl_reset.create_stop_and_go(ccs, None, 2, make_cc(enabled=True, accel=0.5), make_cs(standstill=True), f)
  check("重置：行驶后再次停车可再次触发", len(sends) == 1, f"got {len(sends)}")

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
    sends = []
    for f in range(1000, 1005):
      sends = ctrl_g.create_stop_and_go(ccs, None, 2, make_cc(enabled=True, accel=0.5),
                                        make_cs(standstill=True, gear_shifter=gear), f)
    ok = len(sends) == expect_send
    check(f"{name}：{'代发' if expect_send else '不代发'} RESUME", ok, f"got {len(sends)}")

  # 2.9 挡位限制下的防抖重置：P挡判定后回D挡应可再次触发
  ctrl_pd = make_ctrl(CP_SP=CP_SP)
  sends = []
  for f in range(1100, 1105):
    sends = ctrl_pd.create_stop_and_go(ccs, None, 2, make_cc(enabled=True, accel=0.5),
                                       make_cs(standstill=True, gear_shifter=GS.park), f)
  check("P挡：5帧不代发且计数清零", len(sends) == 0)
  sends = []
  for f in range(1105, 1110):
    sends = ctrl_pd.create_stop_and_go(ccs, None, 2, make_cc(enabled=True, accel=0.5),
                                       make_cs(standstill=True, gear_shifter=GS.drive), f)
  check("P挡后回D挡：5帧确认后触发", len(sends) == 1, f"got {len(sends)}")

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
