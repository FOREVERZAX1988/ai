#!/usr/bin/env python3
"""方案B完整实施（2026-08-19 重新实施，吸取事故教训）：
1. params_keys.h：注册 MacanSlopeComp/MacanSlopeCompUnlimited/MacanSteerParams
2. miciUI toggles.py：加3个开关（MacanStartStop下方，仅Macan可见）
3. mlbcan.py：create_acc_accel_control 加 slope_pct/slope_comp/slope_comp_unlimited 参数（不用CS变量）
4. carcontroller.py：__init__ 读 Params + 调用传参
5. interface.py：_get_params return 前加 MacanSteerParams 覆盖 steerRatio/friction
"""
import py_compile, re

ok = True

# ========== 1. params_keys.h ==========
p1 = "openpilot/common/params_keys.h"
s = open(p1, encoding="utf-8").read()
anchor = '    {"MacanStartStop", {PERSISTENT | BACKUP, BOOL, "0"}},  // Macan 起步跟停（视觉决定起步，OP 代发 RESUME）\n'
assert s.count(anchor) == 1, f"params_keys.h 锚点异常: {s.count(anchor)}"
add = anchor + '''    {"MacanSlopeComp", {PERSISTENT | BACKUP, BOOL, "0"}},          // Macan 坡度补偿开关（下坡刹一脚/上坡加力矩）
    {"MacanSlopeCompUnlimited", {PERSISTENT | BACKUP, BOOL, "0"}}, // 坡度补偿-放开原厂力矩限制（选项2）
    {"MacanSteerParams", {PERSISTENT | BACKUP, BOOL, "0"}},        // Macan 转向系数（实验值，待路试修正）
'''
s = s.replace(anchor, add, 1)
open(p1, "w", encoding="utf-8").write(s)
print("✅ 1. params_keys.h")
py_compile.compile(p1, doraise=True) if p1.endswith(".py") else None

# ========== 2. miciUI toggles.py ==========
p2 = "openpilot/selfdrive/ui/mici/layouts/settings/toggles.py"
s = open(p2, encoding="utf-8").read()
a2 = '    macan_start_stop = BigParamControl(tr("Macan Stop and Go"), "MacanStartStop")\n'
assert s.count(a2) == 1, f"toggles 定义锚点异常: {s.count(a2)}"
add2 = a2 + '''    macan_slope_comp = BigParamControl(tr("Macan Slope Compensation"), "MacanSlopeComp")
    macan_slope_comp_unlimited = BigParamControl(tr("Macan Slope Comp Unlimited"), "MacanSlopeCompUnlimited")
    macan_steer_params = BigParamControl(tr("Macan Steering Params"), "MacanSteerParams")
'''
s = s.replace(a2, add2, 1)
a2b = '      ("MacanStartStop", macan_start_stop),\n'
assert s.count(a2b) == 1, f"toggles tuple 锚点异常: {s.count(a2b)}"
add2b = a2b + '''      ("MacanSlopeComp", macan_slope_comp),
      ("MacanSlopeCompUnlimited", macan_slope_comp_unlimited),
      ("MacanSteerParams", macan_steer_params),
'''
s = s.replace(a2b, add2b, 1)
# 可见性：在 MacanStartStop 可见性块后追加
a2c = '# Macan Stop and Go: only shown for Macan (MLB)'
assert s.count(a2c) >= 1, "toggles 可见性锚点异常"
m = re.search(r'(# Macan Stop and Go.*?\n(?:.*\n)*?.*macan_start_stop\.set_visible\(False\)\n)', s)
if m:
    block = m.group(1)
    add2c = block + '''
    # Macan Slope Comp / Steering Params: only shown for Macan (MLB)
    if self._params.get("MacanSlopeComp") is not None:
      macan_slope_comp.set_visible(True)
      macan_slope_comp_unlimited.set_visible(True)
      macan_steer_params.set_visible(True)
    else:
      macan_slope_comp.set_visible(False)
      macan_slope_comp_unlimited.set_visible(False)
      macan_steer_params.set_visible(False)
'''
    s = s.replace(block, add2c, 1)
    print("✅ 2. miciUI toggles.py")
else:
    print("❌ 2. toggles 可见性块未匹配"); ok = False
open(p2, "w", encoding="utf-8").write(s)

# ========== 3. mlbcan.py ==========
p3 = "opendbc_repo/opendbc/car/volkswagen/mlbcan.py"
s = open(p3, encoding="utf-8").read()
old_sig = "def create_acc_accel_control(packer, bus, acc_type, acc_enabled, accel, acc_control, stopping, starting, esp_hold, v_ego=0, engine_torque=0, stock_esp=False, stock_follow=False, gas_override=False, stock_fv=False, stock_mom=0.0):"
new_sig = "def create_acc_accel_control(packer, bus, acc_type, acc_enabled, accel, acc_control, stopping, starting, esp_hold, v_ego=0, engine_torque=0, stock_esp=False, stock_follow=False, gas_override=False, stock_fv=False, stock_mom=0.0, slope_pct=0.0, slope_comp=False, slope_comp_unlimited=False):"
assert s.count(old_sig) == 1, f"mlbcan 签名锚点异常: {s.count(old_sig)}"
s = s.replace(old_sig, new_sig, 1)
old_g = "  global _last_acc_moment\n  commands = []"
new_g = """  global _last_acc_moment
  commands = []

  # Macan 坡度补偿（2026-08-19 重新实施）：slope_pct 由 carcontroller 经参数传入（非 CS 变量）。
  # accel_eff = accel + g*sin(atan(slope_pct/100))——上坡(正)增加力矩，下坡(负)触发/加深 verz（刹一脚）。
  # 受 MacanSlopeComp 开关控制；原厂限制：slope_comp_unlimited=False=min(stock_mom)（选项1），
  # True=min(max(stock_mom,200))（选项2 放开小坡空间）。
  if slope_comp:
    import math
    accel_eff = accel + 9.81 * math.sin(math.atan(slope_pct / 100.0))
  else:
    accel_eff = accel
"""
assert s.count(old_g) == 1, f"mlbcan global 锚点异常: {s.count(old_g)}"
s = s.replace(old_g, new_g, 1)
old_b = "    braking = accel < -0.05 or stopping or (not gas_override and v_ego < 2.0 and accel <= 0)"
new_b = "    braking = accel_eff < -0.05 or stopping or (not gas_override and v_ego < 2.0 and accel_eff <= 0)"
assert s.count(old_b) == 1, f"mlbcan braking 锚点异常: {s.count(old_b)}"
s = s.replace(old_b, new_b, 1)
old_m1 = "    if accel >= 0:"
new_m1 = "    if accel_eff >= 0:"
assert s.count(old_m1) == 1, f"mlbcan 力矩分支锚点异常: {s.count(old_m1)}"
s = s.replace(old_m1, new_m1, 1)
old_m2 = "      acc_moment = int(min(500, cruise_torque + accel * 85.0))"
new_m2 = "      acc_moment = int(min(500, cruise_torque + accel_eff * 85.0))"
assert s.count(old_m2) == 1, f"mlbcan 力矩正锚点异常: {s.count(old_m2)}"
s = s.replace(old_m2, new_m2, 1)
old_m3 = "      scale = max(0.0, 1.0 + accel * 2.5)"
new_m3 = "      scale = max(0.0, 1.0 + accel_eff * 2.5)"
assert s.count(old_m3) == 1, f"mlbcan 力矩负锚点异常: {s.count(old_m3)}"
s = s.replace(old_m3, new_m3, 1)
old_m4 = "    if stock_mom > 0 and v_ego > 3.0:\n      acc_moment = min(acc_moment, int(stock_mom))"
new_m4 = "    if stock_mom > 0 and v_ego > 3.0:\n      if slope_comp and slope_comp_unlimited:\n        acc_moment = min(acc_moment, int(max(stock_mom, 200.0)))   # 选项2：放开给小坡空间\n      else:\n        acc_moment = min(acc_moment, int(stock_mom))                # 选项1：原厂限制"
assert s.count(old_m4) == 1, f"mlbcan 原厂限制锚点异常: {s.count(old_m4)}"
s = s.replace(old_m4, new_m4, 1)
old_v = "    target_verz = -2.0 if stopping else max(accel, -2.2)  # 原厂实测最深-2.215"
new_v = "    target_verz = -2.0 if stopping else max(accel_eff, -2.2)  # 原厂实测最深-2.215"
assert s.count(old_v) == 1, f"mlbcan verz 锚点异常: {s.count(old_v)}"
s = s.replace(old_v, new_v, 1)
open(p3, "w", encoding="utf-8").write(s)
print("✅ 3. mlbcan.py")
py_compile.compile(p3, doraise=True)

# ========== 4. carcontroller.py ==========
p4 = "opendbc_repo/opendbc/car/volkswagen/carcontroller.py"
s = open(p4, encoding="utf-8").read()
old_i = "    self.packer_pt = CANPacker(dbc_names[Bus.pt])\n    self.aeb_available = not CP.flags & VolkswagenFlags.PQ"
new_i = """    self.packer_pt = CANPacker(dbc_names[Bus.pt])
    self.aeb_available = not CP.flags & VolkswagenFlags.PQ
    # Macan 坡度补偿/转向系数开关（重启生效；opendbc 测试环境无 openpilot 包时安全降级 False）
    try:
      from openpilot.common.params import Params
      self._mp = Params()
      self.slope_comp = self._mp.get_bool("MacanSlopeComp")
      self.slope_comp_unlimited = self._mp.get_bool("MacanSlopeCompUnlimited")
    except Exception:
      self.slope_comp = False
      self.slope_comp_unlimited = False"""
assert s.count(old_i) == 1, f"carcontroller init 锚点异常: {s.count(old_i)}"
s = s.replace(old_i, new_i, 1)
# 调用处传参（MLB 分支）
old_c = """                                                             stock_fv=stock_fv,
                                                             stock_mom=stock_mom))"""
new_c = """                                                             stock_fv=stock_fv,
                                                             stock_mom=stock_mom,
                                                             slope_pct=self.slope_pct,
                                                             slope_comp=self.slope_comp,
                                                             slope_comp_unlimited=self.slope_comp_unlimited))"""
assert s.count(old_c) == 1, f"carcontroller 调用锚点异常: {s.count(old_c)}"
s = s.replace(old_c, new_c, 1)
open(p4, "w", encoding="utf-8").write(s)
print("✅ 4. carcontroller.py")
py_compile.compile(p4, doraise=True)

# ========== 5. interface.py ==========
p5 = "opendbc_repo/opendbc/car/volkswagen/interface.py"
s = open(p5, encoding="utf-8").read()
old_r = "    return ret"
# 只替换 _get_params 的 return（最后一个 return ret 附近）
idx = s.rfind(old_r)
assert idx > 0, "interface return 锚点异常"
new_r = """    # Macan 转向系数开关（实验值18.0/0.52，跨route标定极差22%不可靠，默认关等路试修正）
    if candidate == CAR.PORSCHE_MACAN_MK1:
      try:
        from openpilot.common.params import Params
        if Params().get_bool("MacanSteerParams"):
          ret.steerRatio = 18.0
          if ret.lateralTuning.which() == 'torque':
            ret.lateralTuning.torque.friction = 0.52
      except Exception:
        pass
    return ret"""
s = s[:idx] + new_r + s[idx + len(old_r):]
open(p5, "w", encoding="utf-8").write(s)
print("✅ 5. interface.py")

print(f"\n全部完成: {'✅ 成功' if ok else '⚠️ 部分失败（见上方❌）'}")
