#!/usr/bin/env python3
"""坡度补偿 v2：carstate 解析 ESP_02 + carcontroller 双源交叉校验"""
# carstate.py
p = 'opendbc_repo/opendbc/car/volkswagen/carstate.py'
s = open(p).read()
a1 = "    self.curvature_meas = 0.\n"
b1 = a1 + "    self.esp_laengsbeschl = 0.0  # 原厂 ESP 纵向加速度（ESP_02），坡度补偿 v2 原厂主源\n"
assert a1 in s, "anchor1"
s = s.replace(a1, b1, 1)
a2 = "  def update_mlb(self, pt_cp, cam_cp, ext_cp, alt_cp) -> tuple[structs.CarState, structs.CarStateSP]:\n    ret = structs.CarState()\n"
b2 = a2 + "    # 原厂 ESP 纵向加速度（ESP_02@257 ESP_Laengsbeschl 24|10 scale0.03125 offset-16）——坡度补偿 v2 原厂主源\n    try:\n      self.esp_laengsbeschl = pt_cp.vl[\"ESP_02\"][\"ESP_Laengsbeschl\"]\n    except Exception:\n      pass\n"
assert a2 in s, "anchor2"
s = s.replace(a2, b2, 1)
open(p, 'w').write(s)
print("carstate.py OK")

# carcontroller.py
p2 = 'opendbc_repo/opendbc/car/volkswagen/carcontroller.py'
t = open(p2).read()
c1 = "    self.slope_pct = 0.0\n"
d1 = c1 + "    self.slope_oem_filtered = 0.0  # 原厂坡度低通滤波（v2 双源）\n"
assert c1 in t, "anchor3"
t = t.replace(c1, d1, 1)
c2 = "          can_sends.extend(self.CCS.create_acc_accel_control("
d2_lines = [
  "          # ---- 坡度补偿 v2：原厂 ESP 纵向加速度主源 + IMU 复核（双源交叉校验）----",
  "          slope_imu = self.slope_pct",
  "          esp_laengs = getattr(CS, 'esp_laengsbeschl', 0.0)",
  "          if self.slope_comp:",
  "            # 原厂坡度：ESP 传感器总加速度 - 运动加速度 = 重力分量（车体坐标系，无需 IMU 标定）",
  "            slope_oem = (esp_laengs - CS.out.aEgo) / 9.81 * 100.0",
  "            # 低通滤波（ESP 100Hz，滤掉 aEgo 微分噪声）",
  "            self.slope_oem_filtered = 0.8 * self.slope_oem_filtered + 0.2 * slope_oem",
  "            if abs(self.slope_oem_filtered - slope_imu) < 3.0:",
  "              slope_used = self.slope_oem_filtered  # 原厂主源（车体传感器更准）",
  "            else:",
  "              # 双源不一致 → 降级：取绝对值较小者（保守，防传感器故障误补偿）",
  "              slope_used = slope_imu if abs(slope_imu) < abs(self.slope_oem_filtered) else self.slope_oem_filtered",
  "          else:",
  "            slope_used = slope_imu  # 开关关：保持 v1 行为（mlbcan 端 slope_comp=False 时不补偿）",
  "          can_sends.extend(self.CCS.create_acc_accel_control(",
]
d2 = "\n".join(d2_lines) + "\n"
assert c2 in t, "anchor4"
t = t.replace(c2, d2, 1)
c3 = "slope_pct=self.slope_pct,"
d3 = "slope_pct=slope_used,"
assert c3 in t, "anchor5"
t = t.replace(c3, d3, 1)
open(p2, 'w').write(t)
print("carcontroller.py OK")
