#!/usr/bin/env python3
"""SnG 修复：stop_and_go.py 的 enabled 从"开机固定的 CP_SP.flags"改为
"每 1 秒动态读 Params(MacanStartStop)"——中途开/关开关无需重启 car 进程即生效。
根因：card.py:129 set_car_specific_params 只在 car 进程启动时跑一次，
CP_SP.flags 开机后固定。用户路试中途开开关 → flags 无 STOP_AND_GO → enabled=False
→ sng_resume_ready 永远 False → 从不代发 RESUME（0000004f 段7 aTgt=1.92 实测实锤）。
"""
import re, sys

p = "opendbc_repo/opendbc/sunnypilot/car/volkswagen/stop_and_go.py"
s = open(p, encoding="utf-8").read()

# ---------- 1. __init__ ----------
old_init = '''  def __init__(self, CP: structs.CarParams, CP_SP: structs.CarParamsSP):
    self.CP = CP
    self.CP_SP = CP_SP
    # 平台过滤：仅 Macan(MLB) 生效——其他 VW 平台即使误开开关也不触发（安全兜底）
    self.enabled = (CP.brand == "volkswagen" and CP.carFingerprint == "PORSCHE_MACAN_MK1"
                    and bool(CP_SP.flags & VolkswagenFlagsSP.STOP_AND_GO))

    self.last_standstill_frame = 0'''
new_init = '''  def __init__(self, CP: structs.CarParams, CP_SP: structs.CarParamsSP):
    self.CP = CP
    self.CP_SP = CP_SP
    # 平台过滤：仅 Macan(MLB) 生效——其他 VW 平台即使误开开关也不触发（安全兜底）
    self._platform_ok = (CP.brand == "volkswagen" and CP.carFingerprint == "PORSCHE_MACAN_MK1")
    # 初始 enabled：flags（card 启动时按 MacanStartStop 设置）。若 Params 可达则
    # 以 Params 为准并定时刷新（update_stop_and_go 内每 100 帧）——中途开/关开关
    # 无需重启 car 进程即生效（0000004f 实测根因：CP_SP.flags 开机后固定，
    # 中途开开关 enabled 仍 False，SnG 永不触发）。
    self.enabled = self._platform_ok and bool(CP_SP.flags & VolkswagenFlagsSP.STOP_AND_GO)
    self._mp = None
    try:
      from openpilot.common.params import Params
      self._mp = Params()
      self.enabled = self._platform_ok and self._mp.get_bool("MacanStartStop")
    except Exception:
      pass  # opendbc 测试环境无 openpilot 包：保持 flags 判断

    self._last_refresh_frame = -100  # 首次调用立即刷新
    self.last_standstill_frame = 0'''
assert old_init in s, "old_init not found"
s = s.replace(old_init, new_init)

# ---------- 2. update_stop_and_go 开头：定时刷新 enabled ----------
old_top = '''    if not self.enabled:
      return False

    if not CC.enabled:
      return False'''
new_top = '''    # 每 100 帧（1s）刷新开关状态：中途开/关 MacanStartStop 立即生效，无需重启
    if self._mp is not None and frame - self._last_refresh_frame >= 100:
      self._last_refresh_frame = frame
      try:
        self.enabled = self._platform_ok and self._mp.get_bool("MacanStartStop")
      except Exception:
        pass

    if not self.enabled:
      return False

    if not CC.enabled:
      return False'''
assert old_top in s, "old_top not found"
s = s.replace(old_top, new_top)

open(p, "w", encoding="utf-8").write(s)
print("stop_and_go.py patched OK")
