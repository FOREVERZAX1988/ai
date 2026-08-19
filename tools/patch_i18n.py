#!/usr/bin/env python3
"""翻译补齐（2026-08-19）：
1. torque_settings.py：硬编码 description 包 tr()
2. app_zh-CHS.po / app_zh-CHT.po：补 MADS 刹车踏板描述 + Macan 3开关 + torque 版本描述
"""
import py_compile

# ===== 1. torque_settings.py =====
p1 = "openpilot/selfdrive/ui/sunnypilot/layouts/settings/steering_sub_layouts/torque_settings.py"
s = open(p1, encoding="utf-8").read()
old1 = 'description="Select the version of Torque Control Tune to use."'
new1 = 'description=tr("Select the version of Torque Control Tune to use.")'
assert s.count(old1) == 1, f"torque 锚点: {s.count(old1)}"
s = s.replace(old1, new1, 1)
open(p1, "w", encoding="utf-8").write(s)
py_compile.compile(p1, doraise=True)
print("✅ 1. torque_settings.py 已包 tr()")

# ===== 2. PO 补丁 =====
entries_cn = [
  ("Choose how Automatic Lane Centering (ALC) behaves after the brake pedal is manually pressed in sunnypilot.",
   "选择在 sunnypilot 中手动踩下刹车踏板后，自动车道居中（ALC）的行为方式。"),
  ("Remain Active: ALC will remain active when the brake pedal is pressed.",
   "保持激活：踩下刹车踏板时 ALC 保持激活。"),
  ("Pause: ALC will pause when the brake pedal is pressed.",
   "暂停：踩下刹车踏板时 ALC 暂停。"),
  ("Disengage: ALC will disengage when the brake pedal is pressed.",
   "退出：踩下刹车踏板时 ALC 退出。"),
  ("Slope Compensation (Macan)", "坡度补偿（Macan）"),
  ("Slope Comp Unlimited (Macan)", "坡度补偿放开限制（Macan）"),
  ("Steering Params (Macan)", "转向系数（Macan）"),
  ("Macan Slope Compensation", "Macan 坡度补偿"),
  ("Macan Slope Comp Unlimited", "Macan 坡度补偿放开限制"),
  ("Macan Steering Params", "Macan 转向系数"),
  ("Macan Slope Compensation: when enabled, the IMU slope signal adds g*sin(slope) to the acceleration request - more torque uphill, and a brake tap downhill (prevents forward lurch). Default off = stock behavior. Onroad cycle restart is requested after toggling.",
   "Macan 坡度补偿：启用后，IMU 坡度信号会将 g*sin(坡度) 叠加到加速度请求上——上坡增加力矩，下坡轻点刹车（防止惯性前冲）。默认关闭=原厂行为。切换后请求重新启动 onroad 周期。"),
  ("Macan Slope Comp Unlimited (sub-option): when Slope Compensation is ON, this removes the stock torque cap (option 2: min(max(stock_mom, 200))), giving small slopes room to act. When OFF, the stock cap applies (option 1: min(stock_mom)).",
   "Macan 坡度补偿放开限制（子选项）：当坡度补偿开启时，本选项移除原厂力矩上限（选项2：min(max(stock_mom,200))），给小坡度留出作用空间。关闭时应用原厂上限（选项1：min(stock_mom)）。"),
  ("Macan Steering Params (experimental): when enabled, uses calibrated steerRatio 18.0 / friction 0.52 instead of stock values. Calibration shows 22% cross-route spread and latAccelFactor data is insufficient, so this is EXPERIMENTAL - keep off until field data confirms.",
   "Macan 转向系数（实验性）：启用后使用标定值 steerRatio 18.0 / friction 0.52 替代原厂值。标定显示跨路线差异 22%，且 latAccelFactor 数据不足，因此这是实验功能——请保持关闭，直到路测数据确认。"),
  ("Select the version of Torque Control Tune to use.",
   "选择要使用的扭矩控制调校版本。"),
]
entries_cht = [
  ("Choose how Automatic Lane Centering (ALC) behaves after the brake pedal is manually pressed in sunnypilot.",
   "選擇在 sunnypilot 中手動踩下煞車踏板後，自動車道居中（ALC）的行為方式。"),
  ("Remain Active: ALC will remain active when the brake pedal is pressed.",
   "保持啟用：踩下煞車踏板時 ALC 保持啟用。"),
  ("Pause: ALC will pause when the brake pedal is pressed.",
   "暫停：踩下煞車踏板時 ALC 暫停。"),
  ("Disengage: ALC will disengage when the brake pedal is pressed.",
   "退出：踩下煞車踏板時 ALC 退出。"),
  ("Slope Compensation (Macan)", "坡度補償（Macan）"),
  ("Slope Comp Unlimited (Macan)", "坡度補償放開限制（Macan）"),
  ("Steering Params (Macan)", "轉向係數（Macan）"),
  ("Macan Slope Compensation", "Macan 坡度補償"),
  ("Macan Slope Comp Unlimited", "Macan 坡度補償放開限制"),
  ("Macan Steering Params", "Macan 轉向係數"),
  ("Macan Slope Compensation: when enabled, the IMU slope signal adds g*sin(slope) to the acceleration request - more torque uphill, and a brake tap downhill (prevents forward lurch). Default off = stock behavior. Onroad cycle restart is requested after toggling.",
   "Macan 坡度補償：啟用後，IMU 坡度信號會將 g*sin(坡度) 疊加到加速度請求上——上坡增加力矩，下坡輕點煞車（防止慣性前衝）。預設關閉=原廠行為。切換後請求重新啟動 onroad 週期。"),
  ("Macan Slope Comp Unlimited (sub-option): when Slope Compensation is ON, this removes the stock torque cap (option 2: min(max(stock_mom, 200))), giving small slopes room to act. When OFF, the stock cap applies (option 1: min(stock_mom)).",
   "Macan 坡度補償放開限制（子選項）：當坡度補償開啟時，本選項移除原廠力矩上限（選項2：min(max(stock_mom,200))），給小坡度留出作用空間。關閉時套用原廠上限（選項1：min(stock_mom)）。"),
  ("Macan Steering Params (experimental): when enabled, uses calibrated steerRatio 18.0 / friction 0.52 instead of stock values. Calibration shows 22% cross-route spread and latAccelFactor data is insufficient, so this is EXPERIMENTAL - keep off until field data confirms.",
   "Macan 轉向係數（實驗性）：啟用後使用標定值 steerRatio 18.0 / friction 0.52 取代原廠值。標定顯示跨路線差異 22%，且 latAccelFactor 資料不足，因此這是實驗功能——請保持關閉，直到路測資料確認。"),
  ("Select the version of Torque Control Tune to use.",
   "選擇要使用的扭力控制調校版本。"),
]

for fname, entries in [("openpilot/selfdrive/ui/translations/app_zh-CHS.po", entries_cn),
                       ("openpilot/selfdrive/ui/translations/app_zh-CHT.po", entries_cht)]:
    s = open(fname, encoding="utf-8").read()
    added = 0
    with open(fname, "a", encoding="utf-8") as f:
        for msgid, msgstr in entries:
            if f'msgid "{msgid}"' in s:
                print(f"  ⚠️ 已存在跳过: {msgid[:40]}")
                continue
            f.write(f"\nmsgid \"{msgid}\"\nmsgstr \"{msgstr}\"\n")
            added += 1
    print(f"✅ {fname}: 新增 {added} 条")

print("\n全部完成")
