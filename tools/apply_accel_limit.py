#!/usr/bin/env python3
"""Macan 加速度限制（MacanAccelLimit 参数）：
- params_keys.h: 注册 MacanAccelLimit（FLOAT，"0"=关闭=原厂曲线；>0=自定义上限 m/s²）
- longitudinal_planner.py: get_cruise_accel 里对 Macan 生效 min(max_accel, limit)
  （每1秒刷新缓存读 Params；其他车型不受影响）
默认关（0），路试时设 1.2（数据实锤：4f 激活时间 20% 在 aTarget>1.0、14.7% 在 >1.2）"""

# ========== 1. params_keys.h ==========
p = "openpilot/common/params_keys.h"
s = open(p).read()
old = '''    {"MacanSteerParams", {PERSISTENT | BACKUP, BOOL, "0"}},        // Macan 转向系数（实验值，待路试修正）'''
new = '''    {"MacanSteerParams", {PERSISTENT | BACKUP, BOOL, "0"}},        // Macan 转向系数（实验值，待路试修正）
    {"MacanAccelLimit", {PERSISTENT | BACKUP, FLOAT, "0"}},        // Macan 加速度上限（m/s²，0=原厂曲线；4f实锤 aTarget>1.0 占20%激活时间）'''
assert old in s, "params_keys.h 锚点未找到"
s = s.replace(old, new)
open(p, "w").write(s)
print("params_keys.h OK")

# ========== 2. longitudinal_planner.py ==========
p = "openpilot/selfdrive/controls/lib/longitudinal_planner.py"
s = open(p).read()

old_import = '''import math
import numpy as np'''
new_import = '''import math
import time
import numpy as np'''
assert old_import in s
s = s.replace(old_import, new_import)

old_import2 = '''from openpilot.common.swaglog import cloudlog'''
new_import2 = '''from openpilot.common.swaglog import cloudlog
from openpilot.common.params import Params'''
assert old_import2 in s
s = s.replace(old_import2, new_import2)

old_func = '''def get_max_accel(v_ego):
  return np.interp(v_ego, A_CRUISE_MAX_BP, A_CRUISE_MAX_VALS)'''
new_func = '''def get_max_accel(v_ego):
  return np.interp(v_ego, A_CRUISE_MAX_BP, A_CRUISE_MAX_VALS)

# Macan 加速度限制（MacanAccelLimit 参数，m/s²；0=关闭用原厂曲线）
# 数据依据（0000004f）：激活时间 20.2% 在 aTarget>1.0、14.7% 在 >1.2（低速曲线允许1.6）
# ——起步/跟车加速顶到 1.4-1.6 即"忽然加速"体感来源；限到 1.0-1.2 舒适
_macan_accel_limit = 0.0
_macan_accel_limit_t = 0.0
def _get_macan_accel_limit():
  global _macan_accel_limit, _macan_accel_limit_t
  now = time.monotonic()
  if now - _macan_accel_limit_t > 1.0:  # 每1秒刷新（不阻塞）
    try:
      _macan_accel_limit = Params().get_float("MacanAccelLimit")
    except Exception:
      _macan_accel_limit = 0.0
    _macan_accel_limit_t = now
  return _macan_accel_limit

def _macan_accel_limited(max_accel: float, CP) -> float:
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
assert old_func in s
s = s.replace(old_func, new_func)

old_accel = '''  max_accel = ACCEL_MAX if e2e else get_max_accel(v_ego)'''
new_accel = '''  max_accel = ACCEL_MAX if e2e else get_max_accel(v_ego)
  max_accel = _macan_accel_limited(max_accel, CP)'''
assert old_accel in s
s = s.replace(old_accel, new_accel)
open(p, "w").write(s)
print("longitudinal_planner.py OK")
print("全部完成")
