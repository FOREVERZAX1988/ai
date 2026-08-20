#!/usr/bin/env python3
"""只读分析：Macan 横向"方向盘转动速度"相关的参数链"""
import re, os

base = "/data/openpilot/opendbc_repo/opendbc/car/volkswagen"

# 1. CarControllerParams：STEER_MAX / STEER_STEP / 速率限制
print("=== 1. values.py CarControllerParams ===")
s = open(f"{base}/values.py", encoding="utf-8").read()
for m in re.finditer(r"class CarControllerParams.*?(?=\nclass |\Z)", s, re.S):
    print(m.group(0)[:2500])
    break

# 2. apply_driver_steer_torque_limits 定义位置
print("\n=== 2. apply_driver_steer_torque_limits 定义 ===")
for root, dirs, files in os.walk("/data/openpilot/opendbc_repo/opendbc/car"):
    for fn in files:
        if not fn.endswith(".py"):
            continue
        p = f"{root}/{fn}"
        try:
            t = open(p, encoding="utf-8").read()
        except Exception:
            continue
        if "def apply_driver_steer_torque_limits" in t:
            print(f"位置: {p}")
            # 打印函数体
            idx = t.find("def apply_driver_steer_torque_limits")
            print(t[idx:idx+2600])
            break

# 3. configure_torque_tune 默认参数
print("\n=== 3. configure_torque_tune ===")
t = open("/data/openpilot/opendbc_repo/opendbc/car/interfaces.py", encoding="utf-8").read()
idx = t.find("def configure_torque_tune")
if idx >= 0:
    print(t[idx:idx+1800])
else:
    print("不在 interfaces.py，搜索其他位置...")
    for root, dirs, files in os.walk("/data/openpilot/opendbc_repo/opendbc/car"):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = f"{root}/{fn}"
            try:
                tt = open(p, encoding="utf-8").read()
            except Exception:
                continue
            if "def configure_torque_tune" in tt:
                i2 = tt.find("def configure_torque_tune")
                print(f"位置: {p}")
                print(tt[i2:i2+1800])
                break
