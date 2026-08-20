#!/usr/bin/env python3
"""动态转向比实现（Macan）：
1. car.capnp: CarParams 加 steerRatioV2 @74（[速度km/h..., 比值...]）
2. vehicle_model.py: calc_curvature/get_steer_from_curvature 按速度插值（反馈环用动态SR）
3. interface.py: MacanSteerParams=True 时设置 V2（4f拟合：<144km/h=15.0、>144=18.7）
"""
import os

# ========== 1. car.capnp ==========
p = "opendbc_repo/opendbc/car/car.capnp"
s = open(p).read()
old = """  steerRatio @20 :Float32;      # [] ratio of steering wheel angle to front wheel angle
  steerRatioRear @21 :Float32;  # [] ratio of steering wheel angle to rear wheel angle (usually 0)"""
new = """  steerRatio @20 :Float32;      # [] ratio of steering wheel angle to front wheel angle
  steerRatioRear @21 :Float32;  # [] ratio of steering wheel angle to rear wheel angle (usually 0)
  steerRatioV2 @74 :List(Float32);  # [speed(km/h)..., ratio...] speed-dependent steering ratio (e.g. Porsche PDS)"""
assert old in s, "car.capnp 锚点未找到"
s = s.replace(old, new)
open(p, "w").write(s)
print("car.capnp OK")

# ========== 2. vehicle_model.py ==========
p = "opendbc_repo/opendbc/car/vehicle_model.py"
s = open(p).read()

old_init = """    self.cF_orig: float = CP.tireStiffnessFront
    self.cR_orig: float = CP.tireStiffnessRear
    self.update_params(1.0, CP.steerRatio)"""
new_init = """    self.cF_orig: float = CP.tireStiffnessFront
    self.cR_orig: float = CP.tireStiffnessRear
    self.update_params(1.0, CP.steerRatio)
    # 速度相关转向比（V2）：CP.steerRatioV2 = [speed(km/h)..., ratio...]（前一半速度、后一半比值）
    # Macan 动态转向比（4f 全段 29284 样本拟合：<144km/h SR≈15.0、>144km/h SR≈18.7，PDS 随速特性实锤）
    self._sr_v2_speeds = []
    self._sr_v2_ratios = []
    try:
      v2 = CP.steerRatioV2
      if len(v2) >= 4 and len(v2) % 2 == 0:
        half = len(v2) // 2
        self._sr_v2_speeds = [float(x) for x in v2[:half]]
        self._sr_v2_ratios = [float(x) for x in v2[half:]]
    except Exception:
      pass

  def _dyn_sr(self, u: float) -> float:
    \"\"\"速度相关转向比：u(m/s) → SR，按 km/h 表线性插值；无 V2 时用固定 sR\"\"\"
    if self._sr_v2_speeds:
      return float(np.interp(u * 3.6, self._sr_v2_speeds, self._sr_v2_ratios))
    return self.sR"""
assert old_init in s, "vehicle_model __init__ 锚点未找到"
s = s.replace(old_init, new_init)

old_cc = """    return (self.curvature_factor(u) * sa / self.sR) + self.roll_compensation(roll, u)"""
new_cc = """    return (self.curvature_factor(u) * sa / self._dyn_sr(u)) + self.roll_compensation(roll, u)"""
assert old_cc in s, "calc_curvature 锚点未找到"
s = s.replace(old_cc, new_cc)

old_gs = """    return (curv - self.roll_compensation(roll, u)) * self.sR * 1.0 / self.curvature_factor(u)"""
new_gs = """    return (curv - self.roll_compensation(roll, u)) * self._dyn_sr(u) * 1.0 / self.curvature_factor(u)"""
assert old_gs in s, "get_steer_from_curvature 锚点未找到"
s = s.replace(old_gs, new_gs)
open(p, "w").write(s)
print("vehicle_model.py OK")

# ========== 3. interface.py ==========
p = "opendbc_repo/opendbc/car/volkswagen/interface.py"
s = open(p).read()
old_if = """          ret.steerRatio = 16.2  # v2标定(ESP_Gierrate,4route极差2.6%): 15.24/16.05/17.23/14.65中位≈15.7,与原厂16.2一致; 旧实验值18.0(gyro极差22%)偏大15%→城市弯转向不足
          if ret.lateralTuning.which() == 'torque':"""
new_if = """          ret.steerRatio = 16.2  # v2标定(ESP_Gierrate,4route极差2.6%): 15.24/16.05/17.23/14.65中位≈15.7,与原厂16.2一致; 旧实验值18.0(gyro极差22%)偏大15%→城市弯转向不足
          # 动态转向比（速度相关）：4f全段29284样本拟合——<144km/h SR≈15.0（36-72:14.98/72-144:15.01）、
          # >144km/h SR≈18.71（RMSE1.75°）——保时捷PDS/EPS随速特性实锤（早前v7标定高速段22.9即此）。
          # 格式：[速度km/h..., 比值...]（前一半速度、后一半比值）；140-145km/h线性过渡；
          # 当前16.2为折中（中速偏大8%转向不足、高速偏小13%转向过度——高速段由V2修正）。
          ret.steerRatioV2 = [0.0, 140.0, 145.0, 200.0, 15.0, 15.0, 18.7, 18.7]
          if ret.lateralTuning.which() == 'torque':"""
assert old_if in s, "interface 锚点未找到"
s = s.replace(old_if, new_if)
open(p, "w").write(s)
print("interface.py OK")
print("全部完成")
