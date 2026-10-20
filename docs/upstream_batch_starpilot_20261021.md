# 上游 StarPilot 整批（13 提交）—— 立项与初判

- 立项日期：2026-10-21
- 范围：`upstream/test` 的 **817f4a78c2..2d9c586376**（13 个提交，6,564 insertions / 111 deletions）
- 现状：我们登记表 `upstream_pending_port.scope` 只到 `817f4a78c2`；这 13 个提交**还没进登记表**
- 驾驶者口径：**整批立项、单独评估**，不混进正在搬的单条

## 0. 为什么不能直接一条条往后搬

这 13 个提交不是独立的小改动，而是一整层 StarPilot 特性，且**压在我们尚未移植的 7 条之上**：

- `2d9c586376` 的 `latcontrol_torque.py` 直接 import `latcontrol_vehicle_tunes.py` 和
  `sunnypilot/common/lateral_arbitration.py` —— 前者正是 items 里 **未移植** 的
  `80cd489f0e` 创建的，后者由本批 `44a32ec77c` 创建。
- `44a32ec77c` 又改 `flm_workspace.py` —— 那是 items 里 **未移植** 的 `982fb613f5` 的产物。
- 也就是说：**先搬 items 里的 80cd489f0e / 982fb613f5 / 077456330f，本批才有落点**；
  反过来先搬本批，等于把 items 那 7 条以"影子"形式带进来一半，登记表会失真。

## 1. 逐条初判

| # | 提交 | 体量 | 主要落点 | 与我们已登记分叉的碰撞 | 初判 |
|---|---|---|---|---|---|
| 1 | `0ba6c81d04` ui: dedupe SLA button, webui-only knobs into big UI, zh translations | 5 文件 / +875 | `carrot_tuning_items.py`、`settings/steering.py`、`app_zh-CHS.po`(+737) | **重**：`carrot_tuning_items.py` 是 phase1 已登记分叉文件；我们的 `.po` 是全量 msgid 的自维护版本 | 单独一批（UI/翻译），最后做 |
| 2 | `93b695da88` ui: radar point overlay levels（carrot ShowRadarInfo scale） | 6 文件 / +118 | `onroad/radar_points.py`、`ui_state.py`、`visuals.py` | 中：UI 分叉面，但有 `test_radar_points.py` 可比 | 与 #1 同批 |
| 3 | `045e473a33` uncertainty panic gate + duplicate-lead guard + model lead trajectory | 9 文件 / +1104 | `long_mpc.py`、`longitudinal_planner.py`、新增 3 模块 + 3 测试 | **重**：`long_mpc.py` 已登记分叉 | 纵向批，逐条评估 |
| 4 | `c3ab2803e5` longcontrol stopping-release hysteresis + creep guard | 4 文件 / +281 | `longcontrol.py`、新增 `longcontrol_stop_release.py` | 中重：我们 `stopping_controller.py` 已分叉 | 纵向批 |
| 5 | `d924d11b9b` adjacent-lane stopped-vehicle detector（logic layer） | 3 文件 / +278 | 新增 `adjacent_stop_detector.py`、`radard.py`(+8) | 中：`radard.py` 是我们分叉最重的文件（+8 行钩子） | 纵向批，低风险优先 |
| 6 | `265c29a27d` curve-speed self-learning（Bayesian comfort lateral accel） | 4 文件 / +580 | 新增 `curve_speed_learning.py`、`vision_controller.py` | 轻：新文件为主 | 纵向批 |
| 7 | `63a6f3211b` NNFF lateral neural network feedforward（Twilsonco） | **127 文件 / +742** | 125 个 `assets/nnff_models/<CAR>.json`（各 1 行）+ `NNFFMode` 键 + 运行时 | 轻代码面/重资产面：真正代码很小，资产是逐车型 JSON | 横向批；注意 LFS/体积口径 |
| 8 | `ff32ddccf8` vision lane-centering curvature correction | 4 文件 / +409 | 新增 `lane_centering.py` + `controlsd.py`(+27) | 中：我们有 `LateralLaneCentering` 相关键 | 横向批 |
| 9 | `44a32ec77c` learned-vs-user lateral arbitration + FLM runtime injection | 9 文件 / +752 | `controlsd.py`(+67)、`latcontrol_torque.py`(+63)、新增 `lateral_arbitration*.py` | 中：依赖 #982fb613f5（未移植） | **底座批**，必做前置 |
| 10 | `da20eaaab4` speed-dependent following profiles | 5 文件 / +458 | `following_profile.py`、`long_mpc.py`、`longitudinal_planner.py` | 重：同上两个分叉文件 | 纵向批 |
| 11 | `725bfb210d` weather-conditioned driving offsets | 6 文件 / +318 | `weather_offsets.py`、`longitudinal_planner.py`、`vision_controller.py` | 重：`longitudinal_planner.py` | 纵向批；先问「要不要」（需要外部天气数据源？） |
| 12 | `d4136d1df0` 视觉限速喂进 speed-limit resolver | 4 文件 / +323 | `speed_limit_resolver.py`、新增 `vision_limit.py` | 中：依赖 `d81eec5899`（未移植的 vision speed-limit daemon） | 纵向批，依赖未移植条目 |
| 13 | `2d9c586376` fix: survive an unregistered parameter key instead of killing the daemon | 10 文件 / +326 | 新增 `sunnypilot/common/param_read.py`(+93)、多处 call site | 轻：纯兜底 | **单独、优先**（见 §2） |

## 2. 唯一建议「脱离整批、先做」的一条：`2d9c586376` 的 `param_read.py`

它修的是**我们已经踩到的坑**：`params_keys.h` 编进 `libparams_c.so`，旧库不认新键时
`Params.get()` 抛 `UnknownKeyName`。本轮搬 `b96f079ca8`（CustomKp）时已经实测到：

```
Params().get("CustomKp", return_default=True) -> EXC UnknownKeyName b'CustomKp'
```

我们在 `_read_custom_kp_scale` 里就地加了 try/except 回落 1.0（见 round2 文档 §7）。
上游的 `param_read.py` 是这件事的统一形状（`read_bool` / `read_float`，未注册键回落文档默认值、
其它异常照常抛）。建议：

- 只搬 `openpilot/sunnypilot/common/param_read.py` + 它的 127 行测试（`test_param_read.py`）
  **一个文件对**，不动任何 call site，不引 `lateral_arbitration*`；
- 然后把我们那处 `_read_custom_kp_scale` 的 try/except 换成 `read_float(self.params, "CustomKp", 1.0)`；
- 这样整批将来落地时，这一层依赖已经就位。

## 3. 建议的批次切法

| 批次 | 内容 | 前置 | 风险 |
|---|---|---|---|
| **前置 P** | `2d9c586376` 的 `param_read.py` 模块 + 测试 | 无 | 低 |
| **底座 A** | items 的 `077456330f`（注册键）→ `982fb613f5`（FLM workspace）→ `80cd489f0e`（vehicle tunes）→ 本批 `44a32ec77c`（arbitration） | P | 中；`controlsd.py` 与 `latcontrol_torque.py` 双改 |
| **纵向 B** | `d924d11b9b`（最先，低风险）→ `c3ab2803e5` → `265c29a27d` → `d81eec5899`+`d4136d1df0` → `045e473a33` → `da20eaaab4` → `725bfb210d` | 逐条 | **高**：`long_mpc.py` / `longitudinal_planner.py` / `radard.py` 全是我们分叉最重的文件，需逐条看 Macan 分叉 |
| **横向 C** | `63a6f3211b`（NNFF）、`ff32ddccf8`（vision lane centering） | P | 中；NNFF 有资产体积 |
| **UI D** | `0ba6c81d04`、`93b695da88` | 无 | 中；`carrot_tuning_items.py` 分叉 + `.po` 冲突 |

## 4. 结论与待决策

1. **不建议**在本轮就把整批搬进来 —— 它压着 7 条未移植条目，且碰的文件正是我们分叉最重的三个。
2. **建议立刻做的前置 P**（`param_read.py`）：小、独立、修的是我们已实测到的坑。
3. 批次 B 里 `725bfb210d`（天气修正）要先确认数据源从哪来（是否要外部 API/离线表），
   否则等于埋一个永远不生效的开关。
4. 批次 A 里 `80cd489f0e` 在登记表里原判是「上游 tune 表无 PORSCHE/MACAN，按没有就不搬」，
   但它是 `44a32ec77c`/`2d9c586376` 的 import 前置 —— 这条判据要改：
   **要么搬（Macan 走空表回默认），要么整批不搬**。

## 5. 执行记录

- **2026-10-21 前置 P 已完成**：搬 `2d9c586376` 的
  `openpilot/sunnypilot/common/param_read.py` + `tests/test_param_read.py`，
  与上游逐字节相同（`diff` 为空）。本地提交 `eafa58890d`。
  - 实测：`test_param_read.py` 17 passed；真机 `Params` 探针（非 mock）读未注册键
    回落默认值，不再抛 `UnknownKeyName`。
  - 修正一条过期记录：本机 `libparams_c.so` **已经认识** `CustomKp`
    （`read_float(p, "CustomKp", 1.0)` → 1.0 正常返回），此前「旧库不认该键」的判断
    只代表上一轮 scons 未重建完成时的状态。
  - 仍未做：`latcontrol_torque.py` 里 CustomKp 的就地 `try/except` 收归
    `read_float()`；`2d9c586376` 另外 9 个 call site 随整批（批次 A/B/C）一起搬。
- 结论 §4 第 2 条的 P 已落地，§4 其余待决策项不变。

## 6. items 条目 `80cd489f0e`（车辆横向调参表）—— 已搬（部分）

- 日期：2026-10-21。裁决从「上游无 PORSCHE/MACAN 命中，按没有就不搬」改为
  **搬**（Macan 走空表回默认 = 零影响），以满足 A 批 `44a32ec77c` 的 import 前置。
- 逐字节搬入 4 个文件（`git hash-object` 与上游同 commit blob 一致）：
  - `openpilot/selfdrive/controls/lib/latcontrol_vehicle_tunes.py`（4902 行）
  - `openpilot/sunnypilot/common/testing_grounds.py`（292 行）
  - `openpilot/sunnypilot/selfdrive/controls/lib/vehicle_tune_dispatch.py`（72 行）
  - `openpilot/sunnypilot/selfdrive/controls/lib/tests/test_vehicle_tune_dispatch.py`（49 行）
- `params_keys.h` 增 `VehicleTunesEnabled`（PERSISTENT|BACKUP, BOOL, "0"）；
  `pyproject.toml` 给调参表加 E501 豁免（保持与上游 byte-comparable）。
- **有意不搬**：同提交里 `latcontrol_torque.py` 的 +23/-1 门控钩子。理由：那是 Macan
  路径上分叉最重的文件；钩子做的 ff/friction_threshold/friction_scale/output_scale
  只对注册表内 5 个指纹生效，且 `VehicleTunesEnabled` 默认 0。留到 A 批
  （`44a32ec77c`/`2d9c586376` 触碰同一文件）时一并落，避免在分叉文件上多插一刀。
- 实测（真机、非 mock）：`test_vehicle_tune_dispatch.py` 5 passed；
  `resolve_vehicle_tune(PORSCHE_MACAN) -> None`；registry 5 指纹
  （BOLT_2017=1 / BOLT_2018_2021=1 / ACCORD / GV70_ELECTRIFIED / G70_2020，
  Bolt 2022-2023 三个别名按 `_CAR_ALIASES` 收敛到同一个 `CHEVROLET_BOLT_EUV`）；
  `testing_grounds` 默认 `('1','A')`（无 slots.json 时走默认）。
- `libparams_c.so` 用 `scons -j1 openpilot/common/libparams_c.so` 在 -O0 钉住后重编成功
  （38s，无 LMK）；真机核对 `VehicleTunesEnabled` 注册默认 False、写入/读回往返 True。
- 登记表：items 7→6（本条移入 `ported`，标 `partial`，`deferred` 写明钩子去 A 批）。

## 7. items 条目 `4b21c8cfdb`（stop/depart 策略）—— Step1 已搬（零影响）

- 日期：2026-10-21。按 §3 的两步走建议执行 Step1，**不碰** `longitudinal_planner.py`。
- 逐字节搬入（`git hash-object` == 上游 4b21c8cfdb 的 blob）：
  - `openpilot/selfdrive/controls/lib/lead_stop_depart_policy.py`（1792 行，`249a2d7a50`）
  - `openpilot/selfdrive/controls/lib/tests/test_lead_stop_depart_policy.py`（261 行，`886c2a6103`）
  - `openpilot/selfdrive/controls/lib/longitudinal_vehicle_tunes.py` → 整文件换成上游
    896 行版（`ad2e421c86`）。本树原 16 行 seed 的 `get_far_lead_coast_headway_floor`
    与上游逐字节一致，唯一引用方 `selfdrive/controls/tests/test_lead_behavior.py`
    未改一行；上游版还自带「sp seed accessors」收尾段，注释也一起过来了。
- `params_keys.h` 增 `LeadStopDepartPolicyEnabled`（PERSISTENT|BACKUP, BOOL, "0"），
  紧随 `LeadFollowPolicyEnabled`。
- 零影响证据：
  - `grep -rn lead_stop_depart_policy --include=*.py` → 除自身测试外**无人 import**；
  - `longitudinal_planner.py` 里 `LeadStopDepart|stop_depart` 命中 0，钩子确实没进；
  - 键默认 0（`Params().get` 返回 None → `get_bool` 默认 False）。
- 实测（真机）：`test_lead_stop_depart_policy.py` + `test_lead_behavior.py` **68 passed**；
  `ruff check` 三个新文件全过（无需再加 E501 豁免）。
- `libparams_c.so`：`scons -j1 openpilot/common/libparams_c.so` 在 `-O0` 钉住下 38s 一次过
  （无 LMK），keys 675→**676**，`check_key('LeadStopDepartPolicyEnabled')` OK；
  `sudo systemctl restart comma` 后 manager(683348) 与 `carrot_server`(683725) 的
  `/proc/*/maps` 都指向新副本 `libparams_c-1792540594-2872216.so`；
  `/api/push/status` 返回 `subscriptions: 2`（顺带回归了 Web Push 回 Params 那条）。
- 登记表：items 5→4（本条移入 `ported`，`partial: true`）。
- **Step2（需上路）仍未做**：`longitudinal_planner.py` 的两个 deferred 钩子
  （`LeadFollowPolicyEnabled` + `LeadStopDepartPolicyEnabled`），要按本树
  `carrot_source` / `cutin_predecel` / 红线预减速 的实际顺序手工合并一次，默认关、
  跑通后再验。`deferred_hooks` 里两条探针（`symbol_absent`）保持有效。

## 8. items 条目 `817f4a78c2`（stop/depart 脚本化仿真）—— 已搬

- 日期：2026-10-21。单文件 `scripts/simulate_lead_stop_depart.py`（226 行），
  `git hash-object` == 上游 blob `33d10d502e`，chmod +x。
- 为何此时能独立成立：它的被测对象 `lead_stop_depart_policy.py` 已在 §7 的
  ed7720231c 落地；此前登记表写「没有被测对象」的理由已失效。
- 真机实测（offroad、无 cereal、20Hz 闭环、真机 long_mpc 常量）**5/5 PASS**：

  | 场景 | 结果 |
  |---|---|
  | standstill_depart | launched at 3.70s, min gap 4.50m |
  | approach_brake | braking from 0.0s, min gap 60.6m |
  | low_speed_stop | stopped at 2.8s, final gap 9.2m |
  | radar_gap_settle | settle accel engaged=True, max gap 6.80m |
  | gate_off_passthrough | a_target unchanged without a lead |

- 价值：这是 Step2（planner 钩子）在 offroad 阶段**唯一**能拿到的行为基线 ——
  钩子接上后再跑同一脚本，逐场景对比 depart 时刻/最小间距即可判定有没有改坏。
- 登记表：items 4→3（余下 982fb613f5 / d81eec5899 两条 eval + 077456330f 那条
  纯登记键，随它们走）。
