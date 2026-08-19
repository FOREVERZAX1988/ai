#!/usr/bin/env python3
"""真正修复：坡度补偿子选项（Unlimited）联动可见性——主开关关闭时隐藏。
volkswagen.py（sunnypilot UI）+ mici toggles.py 两处。
"""
import py_compile, re

# ===== 1. volkswagen.py =====
p1 = "openpilot/selfdrive/ui/sunnypilot/layouts/settings/vehicle/brands/volkswagen.py"
s = open(p1, encoding="utf-8").read()

# 1a. update_settings 联动
old = """  def update_settings(self):
    if ui_state.CP is not None:
      # 仅 Macan(MLB) 支持；其他 VW 平台隐藏开关
      is_macan = ui_state.CP.carFingerprint == \"PORSCHE_MACAN_MK1\"
      self.start_stop.action_item.set_enabled(is_macan and not ui_state.engaged)
      self.start_stop.action_item.set_visible(is_macan)
      for item in (self.slope_comp, self.slope_comp_unlimited, self.steer_params):
        item.action_item.set_enabled(is_macan and not ui_state.engaged)
        item.action_item.set_visible(is_macan)"""
new = """  def update_settings(self):
    if ui_state.CP is not None:
      # 仅 Macan(MLB) 支持；其他 VW 平台隐藏开关
      is_macan = ui_state.CP.carFingerprint == \"PORSCHE_MACAN_MK1\"
      slope_comp_on = ui_state.params.get_bool(\"MacanSlopeComp\")
      self.start_stop.action_item.set_enabled(is_macan and not ui_state.engaged)
      self.start_stop.action_item.set_visible(is_macan)
      self.slope_comp.action_item.set_enabled(is_macan and not ui_state.engaged)
      self.slope_comp.action_item.set_visible(is_macan)
      # 子选项（放开限制）：仅坡度补偿开启时显示（联动）
      self.slope_comp_unlimited.action_item.set_enabled(is_macan and not ui_state.engaged and slope_comp_on)
      self.slope_comp_unlimited.action_item.set_visible(is_macan and slope_comp_on)
      self.steer_params.action_item.set_enabled(is_macan and not ui_state.engaged)
      self.steer_params.action_item.set_visible(is_macan)"""
assert s.count(old) == 1, f"volkswagen update_settings 锚点: {s.count(old)}"
s = s.replace(old, new, 1)

# 1b. _on_enable_slope_comp 关闭时重置 unlimited
old2 = """  def _on_enable_slope_comp(self, state: bool):
    ui_state.params.put_bool(\"MacanSlopeComp\", state)
    ui_state.params.put_bool(\"OnroadCycleRequested\", True)"""
new2 = """  def _on_enable_slope_comp(self, state: bool):
    ui_state.params.put_bool(\"MacanSlopeComp\", state)
    if not state:
      ui_state.params.put_bool(\"MacanSlopeCompUnlimited\", False)
      self.slope_comp_unlimited.action_item.set_state(False)
    ui_state.params.put_bool(\"OnroadCycleRequested\", True)"""
assert s.count(old2) == 1, f"volkswagen _on_enable 锚点: {s.count(old2)}"
s = s.replace(old2, new2, 1)
open(p1, "w", encoding="utf-8").write(s)
py_compile.compile(p1, doraise=True)
print("✅ 1. volkswagen.py 联动已写入")

# ===== 2. mici toggles.py =====
p2 = "openpilot/selfdrive/ui/mici/layouts/settings/toggles.py"
s = open(p2, encoding="utf-8").read()
old3 = """    # Macan Stop and Go / Slope Comp / Steering Params: only shown for Macan (MLB)
    if ui_state.CP is not None and ui_state.CP.carFingerprint == \"PORSCHE_MACAN_MK1\":
      self._macan_start_stop.set_visible(True)
      self._macan_slope_comp.set_visible(True)
      self._macan_slope_comp_unlimited.set_visible(True)
      self._macan_steer_params.set_visible(True)
    else:
      self._macan_start_stop.set_visible(False)
      self._macan_slope_comp.set_visible(False)
      self._macan_slope_comp_unlimited.set_visible(False)
      self._macan_steer_params.set_visible(False)"""
new3 = """    # Macan Stop and Go / Slope Comp / Steering Params: only shown for Macan (MLB)
    if ui_state.CP is not None and ui_state.CP.carFingerprint == \"PORSCHE_MACAN_MK1\":
      slope_comp_on = ui_state.params.get_bool(\"MacanSlopeComp\")
      self._macan_start_stop.set_visible(True)
      self._macan_slope_comp.set_visible(True)
      self._macan_slope_comp_unlimited.set_visible(slope_comp_on)
      self._macan_steer_params.set_visible(True)
    else:
      self._macan_start_stop.set_visible(False)
      self._macan_slope_comp.set_visible(False)
      self._macan_slope_comp_unlimited.set_visible(False)
      self._macan_steer_params.set_visible(False)"""
assert s.count(old3) == 1, f"mici 可见性锚点: {s.count(old3)}"
s = s.replace(old3, new3, 1)
open(p2, "w", encoding="utf-8").write(s)
py_compile.compile(p2, doraise=True)
print("✅ 2. mici toggles.py 联动已写入")

# grep 核实
import subprocess
for p in (p1, p2):
    r = subprocess.run(["grep", "-n", "slope_comp_on", p], capture_output=True, text=True)
    print(f"--- {p} slope_comp_on ---")
    print(r.stdout.strip() or "  (无)")
print("\n全部完成")
