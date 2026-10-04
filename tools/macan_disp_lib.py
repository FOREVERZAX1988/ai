"""Macan 仪表车距显示 —— 真实 CarController 驱动库（确定性、无实车依赖）。

用途：把 (原厂雷达 idx, OP 融合 dRel) 逐帧喂给**真实** CarController.update()，
取回该帧发到 bus0 的 ACC_02.ACC_Abstandsindex，用于：
  1) 判定"仪表显示源"到底是原厂 idx 透传 还是 OP 融合 claim 换算；
  2) 日志回放复现（ai/tools/_probe_macan_disp_route.py）；
  3) 后续写成回归用例（不依赖 pytest，unittest 可跑）。
"""
import sys
sys.path.insert(0, '/data/openpilot')

from opendbc.car import structs, Bus
from opendbc.car.car_helpers import interfaces

CAR_NAME = 'PORSCHE_MACAN_MK1'
_FP = dict.fromkeys(range(8), {})


class FakeCarState:
  """controller 需要的 CS 字段；未显式定义的走 0.0 兜底。"""

  def __init__(self, v_ego, stock_idx, stock_obj, op_drel, op_vlead, op_vrel, raw=False):
    self.out = structs.CarState()
    self.out.vEgo = v_ego
    self.out.vEgoRaw = v_ego
    self.out.aEgo = 0.0
    self.out.gasPressed = False
    self.out.brakePressed = False
    self.out.steeringPressed = False
    self.out.steeringTorque = 0.0
    self.out.standstill = v_ego < 0.3
    self.out.accFaulted = False
    self.out.cruiseState.available = True
    self.stock_lead_distance = stock_idx
    self.stock_lead_object = stock_obj
    self.op_lead_dRel = op_drel
    self.op_lead_vLead = op_vlead
    self.op_lead_vRel = op_vrel
    self.stock_zeitluecke = 3
    self.stock_prim_anz = 1
    self.stock_status_anzeige = 3
    self.stock_display_prio = 2
    self.stock_texte_prim = 0
    self.stock_wunschgeschw = 100.0
    self.stock_lead_speed_kph = 60.0
    self.stock_acc04_texte_zusatz = 0
    self.stock_acc04_charisma_status = 1
    self.acc_type = 0
    self.curvature_meas = 0.0
    self.travel_assist_available = False
    self.esp_hold_confirmation = False
    self.gra_stock_values = {'COUNTER': 0, 'LS_Hauptschalter': 1, 'LS_Typ_Hauptschalter': 0,
                             'LS_Codierung': 1, 'LS_Tip_Stufe_2': 0, 'LS_Abbrechen': 0,
                             'LS_Tip_Wiederaufnahme': 0, 'LS_Tip_Setzen': 0, 'LS_Tip_Hoch': 0,
                             'LS_Tip_Runter': 0, 'LS_Verstellung_Zeitluecke': 0}
    self.klr_stock_values = {}
    self.ldw_stock_values = {}
    self.eps_stock_values = {}
    self._raw = raw

  def __getattr__(self, name):
    return 0.0


A = 0.008969
B = 0.332


def idx_of(drel, vego):
  t = drel / vego if vego > 5.0 else drel / 5.0
  return int(round((t - B) / A))


def build_cc():
  """返回 (CarController 实例, CP)。"""
  CI = interfaces[CAR_NAME]
  CP = CI.get_params(CAR_NAME, _FP, [], alpha_long=True, is_release=False, docs=False)
  CP_SP = CI.get_params_sp(CP, CAR_NAME, _FP, [], alpha_long=True, is_release_sp=False, docs=False)
  return CI(CP, CP_SP).CC, CP


def _decode_acc02(sends):
  for addr, dat, bus in sends:
    if addr == 780:
      d = bytes(dat)
      return (d[3] | (d[4] << 8)) & 0x3FF, (d[5] >> 6) & 0x3
  return None, None


def step(cc, v_ego, stock_idx, stock_obj, op_drel, op_vlead=0.0, op_vrel=0.0, frame=0):
  """驱动真实 controller 一帧；返回 (发出的 ab, rele, 迟滞锁 latch)。"""
  cs = FakeCarState(v_ego, stock_idx, stock_obj, op_drel, op_vlead, op_vrel)
  CC = structs.CarControl()
  CC.enabled = True
  CC.longActive = True
  CC.latActive = False
  CC.actuators.accel = 0.0
  CC.cruiseControl.override = False
  CC.hudControl.setSpeed = 30.0
  CC.hudControl.leadVisible = op_drel > 0
  CC.hudControl.leadDistanceBars = 1
  CC.hudControl.visualAlert = structs.CarControl.HUDControl.VisualAlert.none
  CC = CC.as_reader()
  cc.frame = frame * cc.CCP.ACC_HUD_STEP
  sends = cc.update(CC, structs.CarControlSP(), cs, frame * 50_000_000)[1]
  ab, rele = _decode_acc02(sends)
  return ab, rele, cc.disp_src_radar


def reset(cc):
  cc.disp_src_radar = False
  cc.disp_abstand = None
  cc.lead_hold_expire = 0
  cc.lead_hold_distance = 0
