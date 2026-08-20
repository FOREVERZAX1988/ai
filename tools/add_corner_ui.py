#!/usr/bin/env python3
"""Macan 弯道系数 UI 开关改造：params_keys FLOAT→BOOL + planner BOOL化+修bug + sp菜单 + mici UI"""
import re

# ========== 1. params_keys.h: MacanCornerLimit FLOAT -> BOOL ==========
p = "openpilot/common/params_keys.h"
s = open(p).read()
old = '{"MacanCornerLimit", {PERSISTENT | BACKUP, FLOAT, "0"}},       // Macan 弯道纵向限制系数（0=关；>0 时方向盘角>5°线性压低纵向上限，|angle|≥30°上限=限幅×系数；4f实测62%加速发生在弯道）'
new = '{"MacanCornerLimit", {PERSISTENT | BACKUP, BOOL, "0"}},        // Macan 弯道纵向限制开关（BOOL；开=方向盘角>5°线性压低纵向上限，|angle|≥30°压到0.3×当前上限；4f实测62%加速发生在弯道）'
assert old in s, "params_keys.h 原文不匹配"
s = s.replace(old, new)
open(p, "w").write(s)
print("[1] params_keys.h: MacanCornerLimit FLOAT→BOOL ✓")

# ========== 2. planner: BOOL 开关 + 修 max_accel*factor bug ==========
p = "openpilot/selfdrive/controls/lib/longitudinal_planner.py"
s = open(p).read()

old_fn = '''# Macan 弯道系数开关/强度（MacanCornerLimit，0=关；>0=弯道系数下限值 0.3）
# 数据依据（0000004f）：62%加速事件发生在 |angle|>8°；回放验证 0.36-0.85 压限
_macan_corner_min = 0.0
_macan_corner_min_t = 0.0
def _get_macan_corner_min():
  global _macan_corner_min, _macan_corner_min_t
  now = time.monotonic()
  if now - _macan_corner_min_t > 1.0:  # 每1秒刷新（不阻塞）
    try:
      _macan_corner_min = float(Params().get("MacanCornerLimit") or 0.0)
    except Exception:
      _macan_corner_min = 0.0
    _macan_corner_min_t = now
  return _macan_corner_min
'''
new_fn = '''# Macan 弯道系数开关（MacanCornerLimit，BOOL；开=启用，强度下限硬编码 0.3）
# 数据依据（0000004f）：62%加速事件发生在 |angle|>8°；回放验证 0.36-0.85 压限
# 强度参数化待后续（FLOAT 开关需 params 库重编译，暂用常量）
_MACAN_CORNER_MIN = 0.3
_macan_corner_on = False
_macan_corner_on_t = 0.0
def _get_macan_corner_on():
  global _macan_corner_on, _macan_corner_on_t
  now = time.monotonic()
  if now - _macan_corner_on_t > 1.0:  # 每1秒刷新（不阻塞）
    try:
      _macan_corner_on = Params().get("MacanCornerLimit") == "1"
    except Exception:
      _macan_corner_on = False
    _macan_corner_on_t = now
  return _macan_corner_on
'''
assert old_fn in s, "planner 参数函数原文不匹配"
s = s.replace(old_fn, new_fn)

old_app = '''  # Macan 弯道系数：方向盘角 >5° 线性压低纵向上限（解决"头没转正就加速"——4f 实测62%加速在弯道）
  # 独立开关：MacanCornerLimit（FLOAT，0=关；>0=系数下限值，如 0.3）——UI 启停下方按钮
  try:
    if "MACAN" in (getattr(CP, "carFingerprint", "") or "").upper():
      corner = _get_macan_corner_min()
      if corner > 0:
        factor = float(np.clip(1.0 - (abs(angle_steers) - 5.0) / 25.0, corner, 1.0))
        max_accel = min(max_accel, _get_macan_accel_limit() * factor)
  except Exception:
    pass
'''
new_app = '''  # Macan 弯道系数：方向盘角 >5° 线性压低纵向上限（解决"头没转正就加速"——4f 实测62%加速在弯道）
  # 独立开关：MacanCornerLimit（BOOL）——UI 启停下方按钮；基于当前上限（限幅后）缩放，直道 factor=1 不变
  try:
    if "MACAN" in (getattr(CP, "carFingerprint", "") or "").upper() and _get_macan_corner_on():
      factor = float(np.clip(1.0 - (abs(angle_steers) - 5.0) / 25.0, _MACAN_CORNER_MIN, 1.0))
      max_accel = min(max_accel, max_accel * factor)
  except Exception:
    pass
'''
assert old_app in s, "planner 弯道系数应用块原文不匹配"
s = s.replace(old_app, new_app)
open(p, "w").write(s)
print("[2] planner: BOOL开关+max_accel*factor修复 ✓")

# ========== 3. sp 菜单 volkswagen.py: 启停下方加开关 ==========
p = "openpilot/selfdrive/ui/sunnypilot/layouts/settings/vehicle/brands/volkswagen.py"
s = open(p).read()

# 3a. DESCRIPTIONS 加 corner_limit
old_d = "  'steer_params': tr_noop("
new_d = """  'corner_limit': tr_noop(
    'Macan Corner Accel Limit: when enabled, the steering angle (>5 deg) '
    'linearly reduces the longitudinal acceleration cap (down to 0.3x at '
    '30+ deg) - prevents "accelerating before the wheel is straight". '
    'Field data: 62% of accel events happen with |angle|>8 deg. Takes '
    'effect immediately, no restart needed.'
  ),
  'steer_params': tr_noop("""
assert old_d in s, "DESCRIPTIONS 锚点不匹配"
s = s.replace(old_d, new_d, 1)

# 3b. __init__ 里 start_stop 之后插入 corner_limit
old_ss = """    self.slope_comp = toggle_item_sp("""
new_ss = """    self.corner_limit = toggle_item_sp(
      lambda: tr("Corner Accel Limit (Macan)"),
      description=lambda: tr(DESCRIPTIONS["corner_limit"]),
      initial_state=ui_state.params.get_bool("MacanCornerLimit"),
      callback=self._on_enable_corner_limit,
      enabled=lambda: not ui_state.engaged,
    )

    self.slope_comp = toggle_item_sp("""
assert old_ss in s, "start_stop 后锚点不匹配"
s = s.replace(old_ss, new_ss, 1)

# 3c. items 列表：start_stop 之后插入
old_items = """      self.start_stop,
      self.slope_comp,"""
new_items = """      self.start_stop,
      self.corner_limit,
      self.slope_comp,"""
assert old_items in s, "items 锚点不匹配"
s = s.replace(old_items, new_items, 1)

# 3d. callback：加 _on_enable_corner_limit（放在 _on_enable_slope_comp 前）
old_cb = """  def _on_enable_slope_comp(self, state: bool):"""
new_cb = """  def _on_enable_corner_limit(self, state: bool):
    # planner 每 1s 刷新参数，即时生效，无需 onroad cycle 重启
    ui_state.params.put_bool("MacanCornerLimit", state)

  def _on_enable_slope_comp(self, state: bool):"""
assert old_cb in s, "callback 锚点不匹配"
s = s.replace(old_cb, new_cb, 1)

# 3e. update_settings 加 corner_limit 可见性（start_stop 之后）
old_us = """      self.start_stop.action_item.set_enabled(is_macan and not ui_state.engaged)
      self.start_stop.set_visible(is_macan)
      self.slope_comp.action_item.set_enabled(is_macan and not ui_state.engaged)"""
new_us = """      self.start_stop.action_item.set_enabled(is_macan and not ui_state.engaged)
      self.start_stop.set_visible(is_macan)
      self.corner_limit.action_item.set_enabled(is_macan and not ui_state.engaged)
      self.corner_limit.set_visible(is_macan)
      self.slope_comp.action_item.set_enabled(is_macan and not ui_state.engaged)"""
assert old_us in s, "update_settings 锚点不匹配"
s = s.replace(old_us, new_us, 1)

open(p, "w").write(s)
print("[3] sp 菜单 volkswagen.py: 启停下方加 Corner Accel Limit 开关 ✓")

# ========== 4. mici toggles.py: 加 macan_corner_limit ==========
p = "openpilot/selfdrive/ui/mici/layouts/settings/toggles.py"
s = open(p).read()

# 4a. 定义：macan_start_stop 之后
old_m = """    macan_start_stop = BigParamControl(tr("Macan Stop and Go"), "MacanStartStop")
    macan_slope_comp = BigParamControl(tr("Macan Slope Compensation"), "MacanSlopeComp")"""
new_m = """    macan_start_stop = BigParamControl(tr("Macan Stop and Go"), "MacanStartStop")
    macan_corner_limit = BigParamControl(tr("Macan Corner Accel Limit"), "MacanCornerLimit")
    macan_slope_comp = BigParamControl(tr("Macan Slope Compensation"), "MacanSlopeComp")"""
assert old_m in s, "mici 定义锚点不匹配"
s = s.replace(old_m, new_m, 1)

# 4b. add_widgets 列表
old_w = """      macan_start_stop,
      macan_slope_comp,"""
new_w = """      macan_start_stop,
      macan_corner_limit,
      macan_slope_comp,"""
assert old_w in s, "mici add_widgets 锚点不匹配"
s = s.replace(old_w, new_w, 1)

# 4c. self._macan_* 赋值
old_a = """    self._macan_start_stop = macan_start_stop
    self._macan_slope_comp = macan_slope_comp"""
new_a = """    self._macan_start_stop = macan_start_stop
    self._macan_corner_limit = macan_corner_limit
    self._macan_slope_comp = macan_slope_comp"""
assert old_a in s, "mici 赋值锚点不匹配"
s = s.replace(old_a, new_a, 1)

# 4d. _refresh_toggles
old_r = """      ("MacanStartStop", macan_start_stop),
      ("MacanSlopeComp", macan_slope_comp),"""
new_r = """      ("MacanStartStop", macan_start_stop),
      ("MacanCornerLimit", macan_corner_limit),
      ("MacanSlopeComp", macan_slope_comp),"""
assert old_r in s, "mici refresh_toggles 锚点不匹配"
s = s.replace(old_r, new_r, 1)

open(p, "w").write(s)
print("[4] mici toggles.py: 加 Macan Corner Accel Limit ✓")

print("\n全部修改完成，下一步 py_compile 语法检查")
