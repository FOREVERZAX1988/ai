#!/usr/bin/env python3
"""Macan aTarget 死区（MacanAccelDeadzone 参数）：
- params_keys.h: 注册 MacanAccelDeadzone（FLOAT，"0"=关；>0=死区值 m/s²）
- longitudinal_planner.py: update 输出处对 Macan 应用死区（|aTarget|<dz 归零）
机制（4f 段7 帧97000-97700 实锤）：MPC 在 0 附近微抖动（+0.04→-0.06 来回过零），
mom 在巡航维持(~95)与滑行(0)之间跳变 = "喘气/一冲一冲"体感；死区归零后 mom 稳定在巡航基线"""
import subprocess

# ========== 1. params_keys.h ==========
p = "openpilot/common/params_keys.h"
s = open(p).read()
old = '''    {"MacanAccelLimit", {PERSISTENT | BACKUP, FLOAT, "0"}},        // Macan 加速度上限（m/s²，0=原厂曲线；4f实锤 aTarget>1.0 占20%激活时间）'''
new = '''    {"MacanAccelLimit", {PERSISTENT | BACKUP, FLOAT, "0"}},        // Macan 加速度上限（m/s²，0=原厂曲线；4f实锤 aTarget>1.0 占20%激活时间）
    {"MacanAccelDeadzone", {PERSISTENT | BACKUP, FLOAT, "0"}},     // Macan aTarget死区（m/s²，0=关；±0.1内归零滤MPC抖动，防mom开合喘气）'''
assert old in s, "params_keys.h 锚点未找到"
s = s.replace(old, new)
open(p, "w").write(s)
print("params_keys.h OK")

# ========== 2. longitudinal_planner.py ==========
p = "openpilot/selfdrive/controls/lib/longitudinal_planner.py"
s = open(p).read()

old_func = '''def _macan_accel_limited(max_accel: float, CP) -> float:
  """对 Macan 应用自定义加速度上限（其他车不受影响）"""
  try:
    fp = CP.carFingerprint.upper()
  except Exception:
    return max_accel
  if "MACAN" not in fp:
    return max_accel
  lim = _get_macan_accel_limit()
  if lim > 0:
    return min(max_accel, lim)
  return max_accel'''
new_func = '''def _macan_accel_limited(max_accel: float, CP) -> float:
  """对 Macan 应用自定义加速度上限（其他车不受影响）"""
  try:
    fp = CP.carFingerprint.upper()
  except Exception:
    return max_accel
  if "MACAN" not in fp:
    return max_accel
  lim = _get_macan_accel_limit()
  if lim > 0:
    return min(max_accel, lim)
  return max_accel

# Macan aTarget 死区（MacanAccelDeadzone，m/s²；0=关闭）
# 机制实锤（0000004f 段7 帧97000-97700）：MPC 在 0 附近微抖动（+0.04→-0.06 来回过零），
# aTarget 过零时 mom 在巡航维持(~95)与滑行(0)之间跳变 = "喘气/一冲一冲"体感
_macan_deadzone = 0.0
_macan_deadzone_t = 0.0
def _get_macan_deadzone():
  global _macan_deadzone, _macan_deadzone_t
  now = time.monotonic()
  if now - _macan_deadzone_t > 1.0:  # 每1秒刷新
    try:
      _macan_deadzone = float(Params().get("MacanAccelDeadzone") or 0.0)
    except Exception:
      _macan_deadzone = 0.0
    _macan_deadzone_t = now
  return _macan_deadzone'''
assert old_func in s, "planner 函数锚点未找到"
s = s.replace(old_func, new_func)

old_out = '''    self.output_a_target = np.clip(output_a_target, ACCEL_MIN, ACCEL_MAX)'''
new_out = '''    self.output_a_target = np.clip(output_a_target, ACCEL_MIN, ACCEL_MAX)
    # Macan aTarget 死区：|aTarget|<dz 归零（滤 MPC 0附近抖动，防 mom 开合喘气；其他车不受影响）
    if "MACAN" in (self.CP.carFingerprint or "").upper():
      dz = _get_macan_deadzone()
      if dz > 0 and abs(self.output_a_target) < dz:
        self.output_a_target = 0.0'''
assert old_out in s, "planner 输出锚点未找到"
s = s.replace(old_out, new_out)
open(p, "w").write(s)
print("longitudinal_planner.py OK")
print("全部修改完成")
