#!/usr/bin/env python3
"""
Macan / VW 仿真回归测试工具（一键跑全套）

用途：修改了驾驶逻辑（carcontroller / carstate / cruise / latcontrol / buttons 等）后，
在设备或 PC 上快速回归，确认没有破坏：
  1. 车型接口（CarInterface / fingerprint）—— 含 PORSCHE_MACAN_MK1
  2. 巡航速度逻辑（VCruiseHelper：SET/RESUME/边沿激活/踩油门）
  3. 按键事件（cruise_mode 长按切实验模式、custom_cruise、button_state_tracker）

运行方式（设备 venv 只读装不了 pytest，统一用 unittest 方式）：
  cd /data/openpilot && python3 ai/tools/sim_test_macan.py
  # 或 PC 上带 pytest：python3 -m pytest -k volkswagen 更全

退出码：0=全部通过；1=有失败（详见输出）
"""

import subprocess
import sys
import os

OPENPILOT_ROOT = "/data/openpilot"


def run_unittest(target: str, desc: str, timeout: int = 300) -> bool:
    """用 unittest 方式跑一个测试类/模块，返回是否通过"""
    print(f"\n{'='*60}\n▶ {desc}\n   target: {target}\n{'='*60}")
    cmd = [sys.executable, "-m", "unittest", target, "-v"]
    r = subprocess.run(cmd, cwd=OPENPILOT_ROOT, timeout=timeout,
                       capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    # 打印关键行
    for line in out.splitlines():
        if any(k in line for k in ("Ran ", "OK", "FAILED", "FAIL:", "ERROR:", "skipped=", "failures=")):
            print("  ", line)
    if r.returncode != 0:
        print("  ❌ 失败，尾部输出：")
        for line in out.splitlines()[-15:]:
            print("    ", line)
    else:
        print("  ✅ 通过")
    return r.returncode == 0


def main() -> int:
    # 平台检测（允许在 PC 上通过 OPENPILOT_ROOT 覆盖）
    root = os.environ.get("OPENPILOT_ROOT", OPENPILOT_ROOT)
    if not os.path.isdir(os.path.join(root, "openpilot")):
        print(f"❌ 找不到 openpilot 源码根: {root}")
        return 2

    results = [
        # (unittest target, 描述)
        ("openpilot.selfdrive.car.tests.test_car_interfaces.TestCarInterfaces.test_car_interfaces_193_PORSCHE_MACAN_MK1",
         "Macan 车型接口 + fingerprint（第193个平台，含 PORSCHE_MACAN_MK1）"),
        ("openpilot.selfdrive.car.tests.test_cruise_speed",
         "巡航速度逻辑（VCruiseHelper：SET初始化/RESUME/边沿激活/踩油门）"),
        ("openpilot.sunnypilot.selfdrive.car.tests.test_cruise_mode",
         "按键事件-巡航模式（长按 Dist+ 切实验模式等，已适配 Macan altButton2）"),
        ("openpilot.sunnypilot.selfdrive.car.tests.test_custom_cruise",
         "按键事件-自定义巡航（智能巡航按钮管理）"),
        ("openpilot.sunnypilot.selfdrive.selfdrived.tests.test_button_state_tracker",
         "按键事件-按钮状态跟踪器"),
    ]

    ok = True
    for target, desc in results:
        try:
            passed = run_unittest(target, desc)
        except subprocess.TimeoutExpired:
            print(f"  ⏱️ 超时（{target}），视为失败")
            passed = False
        ok = ok and passed

    print("\n" + "=" * 60)
    if ok:
        print("🎉 全部仿真回归测试通过（Macan 驾驶逻辑无回归）")
        return 0
    else:
        print("❌ 有仿真测试失败！请先修复再上车/推送。")
        print("   提示：pytest -k volkswagen 可在 PC 上跑更全的车型接口测试")
        return 1


if __name__ == "__main__":
    sys.exit(main())
