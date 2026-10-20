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
