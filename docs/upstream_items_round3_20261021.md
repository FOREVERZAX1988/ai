# items 第三轮（2026-10-21）：横向调参表 + 跟车策略底座

登记表 `upstream_pending_port.items` 从 7 条收到 5 条；本轮两条都是「零影响落地」形状：
新增模块 + 测试 + 注册键（默认关/默认 1.0），**planner 钩子一律不动**。

## 1. `80cd489f0e` 车辆横向调参库 + 门控分发（partial）

- 逐字节搬入（`git hash-object` == 上游 blob）：
  - `openpilot/selfdrive/controls/lib/latcontrol_vehicle_tunes.py`（4902 行）
  - `openpilot/sunnypilot/common/testing_grounds.py`（292 行）
  - `openpilot/sunnypilot/selfdrive/controls/lib/vehicle_tune_dispatch.py`（72 行）
  - `openpilot/sunnypilot/selfdrive/controls/lib/tests/test_vehicle_tune_dispatch.py`（49 行）
- `params_keys.h`：`VehicleTunesEnabled`（PERSISTENT|BACKUP, BOOL, "0"）；
  `pyproject.toml`：调参表 E501 豁免（保持 byte-comparable）。
- 不搬 `latcontrol_torque.py` 的 +23/-1 门控钩子 → 留 A 批（`44a32ec77c`/`2d9c586376` 同文件）。
- 实测：`test_vehicle_tune_dispatch.py` 5 passed；真机 `resolve_vehicle_tune(PORSCHE_MACAN) -> None`；
  registry 5 指纹（Bolt 2022-2023 三别名收敛到 `CHEVROLET_BOLT_EUV`）；
  `testing_grounds` 无 slots.json 时默认 `('1','A')`。

## 2. `51caaa4a3a` 非紧急跟车策略（partial）

- 逐字节搬入 `lead_follow_policy.py`（261 行）+ `test_lead_follow_policy.py`（97 行）；
  `params_keys.h`：`LeadFollowPolicyEnabled`（BOOL, "0"）。
- 不搬 `longitudinal_planner.py` 的 +23 钩子 → 与下一条的手工合并一次做完。
- 实测：`test_lead_follow_policy.py` + `test_lead_behavior.py` 50 passed；ruff 全过。
- 适配核对：`_lead_present` 同时读 `present`/`status`，所以上游用 `status=True` 的用例在本树成立。

## 3. `4b21c8cfdb` stop/depart 策略 —— 只读评估（未动代码）

按驾驶者口径「先只读它的接近段再定」，结论：

1. **接近段本体 harmless**：`get_vision_lead_approach_cap` 是纯函数，只收紧不放松
   （返回 `max(accel_min, -approach_decel)`，一个刹车帽）。门槛四重：视觉前车
   （`lead.radar` 为 True 直接返回 None）、`modelProb>=0.85`、投影接近速度 `>=2.0 m/s`、
   距紧跟随窗口 `<4.5 s` 且在 `desired_gap+2.0` 内；`approach_decel < 0.15` 时干脆不生效。
   Macan 是雷达前车，基本不进入该分支。
2. 同段的 `untracked_slow_lead` / `approach_lift` / `close_stop*` 也都是「更早刹、更稳停」方向。
3. **真正落点在 planner 钩子（+36/-2）**，其上下文锚点是上游的 `LeadFollowPolicyEnabled` 阶段 ——
   本树原先没有该阶段，所以那条 diff 无法原样应用；现在 `51caaa4a3a` 的模块已落地，钩子需要
   按本树 `carrot_source` / `cutin_predecel` / 红线预减速 的实际顺序重写（上游注释自己就写明
   红线预减速在其之后跑，可能覆盖 `a_target`）。
4. `longitudinal_vehicle_tunes.py` 的 885/-5 是整文件替换：上游 890 行版本里
   `get_far_lead_coast_headway_floor` 与我们 8 行 seed 逐字节一致；本树唯一引用方是
   `test_lead_behavior.py`，替换风险低。

**建议两步走**：Step1（零影响）= 搬 `lead_stop_depart_policy.py`(1792 行) +
`test_lead_stop_depart_policy.py`(261 行) + 整文件换 `longitudinal_vehicle_tunes.py` +
注册 `LeadStopDepartPolicyEnabled`（默认 0），不碰 planner；Step2（需上路）= 两个 deferred
钩子（LeadFollowPolicy / LeadStopDepartPolicy）一次性按本树顺序重写，默认关，跑通后再验。
