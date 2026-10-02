# 仿真回归测试（Macan / VW）

## 触发条件（必须跑）

**修改了驾驶逻辑**后，必须跑一遍仿真回归测试确认无回归：
- carcontroller / carstate / car_events（按键、ACC_05 代发、仲裁）
- cruise / cruise_helpers（SET/RESUME/边沿激活/实验模式切换）
- latcontrol（EPS 补偿、扭矩）
- longitudinal_planner（绿灯起步、lead_ready、boost）
- opendbc values.py 按键映射（ButtonType 改动）

## 一键工具

```bash
cd /data/openpilot && python3 ai/tools/sim_test_macan.py
```

覆盖 5 组测试（unittest 方式，设备 venv 只读无需 pytest）：
1. `test_car_interfaces_193_PORSCHE_MACAN_MK1` — 车型接口+fingerprint
2. `test_cruise_speed` — 巡航速度（SET初始化/RESUME/边沿激活/踩油门）
3. `test_cruise_mode` — 长按 Dist+(altButton2) 切实验模式（已适配 Macan）
4. `test_custom_cruise` — 智能巡航按钮管理
5. `test_button_state_tracker` — 按钮状态跟踪器

退出码：0=全过；1=有失败；2=找不到源码根。

## 单测排查

- 设备无 pytest（venv 只读）→ 用 `python3 -m unittest <target> -v`
- Macan 专属测试名：动态解析（当前 `test_car_interfaces_225_PORSCHE_MACAN_MK1`，序号随上游车型增减漂移，勿硬编码）
- PC 全量：`pytest selfdrive/car/tests/test_car_interfaces.py -k volkswagen`

## 自动化程度说明（2026-10-02 修复）

- **Macan 接口测试名不再硬编码**：`sim_test_macan.py` 原先写死
  `test_car_interfaces_193_PORSCHE_MACAN_MK1`，上游并入新车型后平台序号漂移到 **225**，
  该用例变成 `AttributeError: has no attribute` —— 即"最重要的 Macan 接口测试静默不跑"（假红）。
  现改为从 `TestCarInterfaces` 实际生成的方法名动态反查（`detect_macan_interface_test()`），
  找不到则直接退出码 2 报错，不再伪装成通过。
- **SKIP 语义**：`skip_reason()` 只对"已知环境/版本错位"用例（当前仅 `test_custom_cruise`，
  opendbc pin 缺 SP 虚拟巡航按钮 API）打 SKIP 并列出理由，**不计为失败**；
  真回归仍会让退出码非 0。详见 `ai/docs/SUBMODULE_PIN_SKEW.md`。

## 已知适配差异（测试需跟随代码）

- **长按切实验模式按钮**：Macan 适配用 `altButton2`（值2=Dist+1 拉远方向，保守误触安全），
  上游测试用 `gapAdjustCruise`。**改按键映射时必须同步 `test_cruise_mode.py`**，否则测试红。

## 工作流

1. 改代码 → `python3 ai/tools/sim_test_macan.py`
2. 全绿 → 上车路试；有红 → 先修
3. 推送前确认：`sim_test_macan.py` 工具本身改过也要重跑自测

## 相关文档

- `ai/tools/sim_test_macan_sng.py` —— SnG（RESUME 代发）专项 50 用例。
  构造 `CarParams` 时**必须**带 `openpilotLongitudinalControl=True`（2026-09-07 起的门控），
  否则 `enabled` 恒为 False、所有"应代发"用例假红（got 0）。

- `ai/docs/PUBLISH.md` — 推送流程
- `MEMORY.md` 「Macan 按键映射」— altButton2 设计意图
