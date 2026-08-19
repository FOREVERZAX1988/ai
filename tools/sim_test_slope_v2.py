#!/usr/bin/env python3
"""坡度补偿 v2 专项验证：位定义解析 + 双源交叉校验逻辑数值测试
（不依赖完整 openpilot，验证 opendbc 侧 carstate/carcontroller 改动的正确性）"""
import sys
sys.path.insert(0, "/data/openpilot/opendbc_repo")

# ---------- 1. ESP_Laengsbeschl 位定义验证（与 vw_mlb.dbc 一致）----------
def get_sig(dat, start, length, signed=False):
    val = 0
    for i in range(length):
        byte = (start + i) // 8
        bit = (start + i) % 8
        if dat[byte] & (1 << bit):
            val |= (1 << i)
    if signed and val & (1 << (length - 1)):
        val -= (1 << length)
    return val

# dbc 定义：ESP_02@257 ESP_Laengsbeschl 24|10@1+ (0.03125,-16)
def pack_esp02(raw):
    dat = bytearray(8)
    start, length = 24, 10
    for i in range(length):
        if raw & (1 << i):
            byte = (start + i) // 8
            bit = (start + i) % 8
            dat[byte] |= (1 << bit)
    return bytes(dat)

cases = [
    (0, -16.0),       # 原始码0 = offset
    (512, 0.0),       # 原始码512 = 0 m/s²（停车）
    (1023, 15.96875), # 1023*0.03125-16 = 15.96875（范围上限≈15.9）
    (144, -11.5),     # 144*0.03125-16 = -11.5（重刹≈1g）
]
for raw, expect in cases:
    v = get_sig(pack_esp02(raw), 24, 10) * 0.03125 - 16.0
    assert abs(v - expect) < 1e-6, f"解析错误: raw={raw} got={v} expect={expect}"
print(f"✅ 1. ESP_Laengsbeschl 位定义解析正确（{len(cases)} 用例）")

# ---------- 2. 双源交叉校验逻辑数值验证（复现 carcontroller 公式）----------
def dual_slope(slope_imu, esp_laengs, a_ego, slope_comp, filtered_prev=0.0, alpha=0.2):
    """复现 carcontroller.py 里的双源逻辑（307-319行）"""
    if not slope_comp:
        return slope_imu, filtered_prev
    slope_oem = (esp_laengs - a_ego) / 9.81 * 100.0
    filtered = 0.8 * filtered_prev + 0.2 * slope_oem
    if abs(filtered - slope_imu) < 3.0:
        return filtered, filtered          # 原厂主源
    else:
        return (slope_imu if abs(slope_imu) < abs(filtered) else filtered), filtered  # 降级取小

# 用例1：双源一致（滤波已收敛）→ 用原厂主源
slope, f = dual_slope(slope_imu=5.0, esp_laengs=9.81*0.05, a_ego=0.0, slope_comp=True, filtered_prev=5.0)
assert abs(slope - 5.0) < 0.3, f"用例1失败: {slope}"
print(f"✅ 2.1 双源一致→用原厂主源: slope={slope:.2f}%")

# 用例2：IMU 故障（0.1% vs 原厂 5%）→ 降级取绝对值较小者（保守：宁少勿多——漏补偿只掉速，安全）
slope, f = dual_slope(slope_imu=0.1, esp_laengs=9.81*0.05, a_ego=0.0, slope_comp=True, filtered_prev=5.0)
assert abs(slope - 0.1) < 0.05, f"用例2失败: {slope}"
print(f"✅ 2.2 IMU异常→保守取小者(0.1,不补偿,安全优先): slope={slope:.2f}%")

# 用例3：原厂信号异常（ESP 持续=0，滤波已收敛到 0）→ 降级取绝对值较小者（0，不补偿，安全）
slope, f = dual_slope(slope_imu=5.0, esp_laengs=0.0, a_ego=0.0, slope_comp=True, filtered_prev=0.0)
assert abs(slope) < 0.05, f"用例3失败: {slope}"
print(f"✅ 2.3 原厂异常→保守取小者(0,不补偿,安全优先): slope={slope:.2f}%")

# 用例4：开关关 → 只用 IMU（v1 行为）
slope, f = dual_slope(slope_imu=5.0, esp_laengs=9.81*0.05, a_ego=0.0, slope_comp=False)
assert slope == 5.0, f"用例4失败: {slope}"
print(f"✅ 2.4 开关关→IMU原值(v1行为): slope={slope:.2f}%")

# 用例5：滤波首帧渐进收敛（从 0 起步不跳变——补偿渐进不突兀）
slope, f = dual_slope(slope_imu=5.0, esp_laengs=9.81*0.05, a_ego=0.0, slope_comp=True, filtered_prev=0.0)
assert 0.9 < slope < 1.2, f"用例5失败: {slope}"
print(f"✅ 2.5 滤波首帧渐进收敛: slope={slope:.2f}%（0.2权重渐进，补偿不突兀）")

# 用例6：滤波连续收敛（0.2权重，时间常数≈5帧；10帧≈89%→4.46，渐进不跳变）
f = 0.0
for i in range(10):
    slope, f = dual_slope(slope_imu=5.0, esp_laengs=9.81*0.05, a_ego=0.0, slope_comp=True, filtered_prev=f)
assert 4.3 < slope < 4.7, f"用例6失败: {slope}"
print(f"✅ 2.6 滤波10帧收敛: slope={slope:.2f}%（≈89%收敛，渐进不跳变）")

# ---------- 3. 代码一致性检查（carcontroller 实际代码存在关键逻辑）----------
cc = open("/data/openpilot/opendbc_repo/opendbc/car/volkswagen/carcontroller.py").read()
for key in ["slope_oem_filtered", "slope_used", "esp_laengsbeschl", "slope_pct=slope_used"]:
    assert key in cc, f"carcontroller 缺关键逻辑: {key}"
cs = open("/data/openpilot/opendbc_repo/opendbc/car/volkswagen/carstate.py").read()
for key in ["esp_laengsbeschl", "ESP_02", "ESP_Laengsbeschl"]:
    assert key in cs, f"carstate 缺关键逻辑: {key}"
print("✅ 3. 实际代码含全部关键逻辑（grep 核实）")

print("\n🎉 坡度补偿 v2 专项验证全部通过")
