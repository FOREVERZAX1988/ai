# 上游搬运 第 13 轮（2026-10-21）

基线：本树 `sync/upstream-1019`。上一轮（round 12）已把 `d81eec5899` 视觉限速 + `d4136d1df0` 接进解析器。

## 1. 上游增量扫描

`git fetch --all` 之后：`upstream/test` 72c6200b79 → **1952394252（仅 1 个提交）**，
是一次 **webui 子模块指针 bump**（`490b46fdd3 → 0ec403f435`），不是 openpilot 代码。
`upstream/master` 另有 0120b66f05→922513f312，与本树基线无关。

子模块里实际带进 3 条：

| commit | 内容 |
|---|---|
| 490b46f | catalog 按声明的调参深度生成面板；把四个"其实能用"的控件放回来（`SteerRatioRate` / `UseLaneLineCurveSpeed` / `ShowRadarInfo` / `HotspotOnBoot`），并新增契约测试：隐藏的控件必须**没有读者**，或者必须写明理由 |
| 0ec403f | 子面板也打深度标记，不只根面板 |
| d35517c | `CarrotLongitudinalSourceEnabled` 白名单（本树已有等价提交 8ae8e69） |

我们 fork 落后 3、领先 20，merge 冲突只在 `server/bridge/tests/test_panel_catalog.py`：
两边各自换了取 `config.py` 的方式与 import。保留本树的 `_find_config_py()`（我们的树嵌在 `openpilot/` 下），
`Path` 与 `mock` 两个 import 都留。

**上游这次的新测试抓到一个真缺陷**：`CustomSR` 被列进"无读者所以隐藏"，但
`sunnypilot/common/lateral_arbitration_params.py` 读它，而且**非 0 时优先于 `SteerRatio`** ——
也就是说以前在 Carrot app 里设过一次，就会静默压过网页上的 Steer Ratio 输入框，屏上却看不到这个键。
现在 `CustomSR` 与 `Steer Ratio Rate` 并排显示（整数 x0.1，0=未设），描述里写明优先级。
`ShowRadarInfo` 看似无人读，其实被 carrot web 的 `road_overlay_lead_renderer.js` 读（画雷达点），所以放回来是对的；
`HotspotOnBoot` 上游也只是上报 `tethering_enabled`，没有开机动作，这条是上游自身的空转，不属我们的分叉。

## 2. 本轮搬的 openpilot 提交

### 927498237f → 本树 2bfba26c93（`selfdrived` 两档 modeldLagging）

上游实测（route 00000226，76 分钟）：modeld 消费循环贴着 50 ms 帧预算跑（publish-dt p90 = 55–57 ms），
相位漂移时 conflate 队列吃掉正要读的那帧、循环跳过一帧自愈；簇发漂移会让 2 s 低通读到 5–12%。
原来的 5% 阈值 + 1 s 保持会把这种"控制器完全无感的抖动"判成 `SOFT_DISABLE`「立即接管控制」，
上游那条路上 9 次告警里 8 次是接管级。

- 新文件 `selfdrive/selfdrived/modeld_lag.py`：`ModeldLagMonitor`，纯 stdlib（不拉 swaglog/fcntl 链，任何机器可跑单测）。
  severe = 低通 > 20% 持续 1 s（上游原语义，**唯一**允许软禁用的档）；mild = > 10% 持续 2 s（仅信息）。
  高于 severe 时 mild 计数清零，两档不会叠着报。
- `cereal/log.capnp`：`OnroadEvent` 新增 `modeldLaggingMild @106`。本树原本最大序号是 `torqueNNLoad @105`，
  106 空着。**只改 schema**：`gen/cpp/log.capnp.h` 按先例不重建（它连 @104/@105 都没有），C++ 侧无人写这个枚举。
- `events.py`：`modeldLaggingMild` 只挂 `ET.PERMANENT`，**故意不给** `SOFT_DISABLE` / `NO_ENTRY`。
- `selfdrived.py`：`modeld_lag_counter` → `ModeldLagMonitor`，`MODEL_LAG_HOLD_S` 搬进 `modeld_lag.py`。

**对 Macan 的行为变化（单向、正是要的）**：接管级「驾驶模型滞后」从 >5% 持续 1 s 抬到 >20% 持续 1 s；
5–20% 的簇发只出文案相同的信息档。

验证：`selfdrive/selfdrived/tests` **41 passed**（上游 6 条 monitor 用例 + 本树新增 3 条护栏：
mild 档只许有 PERMANENT 钩子、severe 档两个接管钩子必须在、`selfdrived.py` 必须仍调用 monitor 且不得残留
`modeld_lag_counter` —— 以后谁把 mild 提升成打断档或改名，测试立刻红）。

## 3. 登记表现状

`ai/scripts/upstream_divergence_check.py --ref upstream/test`：
phase 1 **24/24**、phase 2 **1/1**（只剩 NNFF）、phase 3 **4/4**，全绿。

`upstream_pending_port.items` 现在只剩 **63a6f3211b（StarPilot NNFF 横向前馈）**，
127 个文件（125 个车型 nnff_models JSON）+ latcontrol 侧推理，体积与延迟要驾驶者拍板，模型资产需 LFS/分块推。
它是登记表里最后一条，也意味着 4630b96a77 之后的上游 test 已全部对齐。

## 4. 剩余待办（都需要驾驶者）

路试/验收类：terminal stop 入口斜率（END_SOFT_RATE 0.4）、无前车 terminal stop 深度与 stopping 期 latch 的 A/B、
`Carrot Longitudinal Source` 开关、Web Push 手机侧 https、视觉限速三行开关（round 12）。
拍板类：AlwaysOnDM 门控、`VisionSpeedLimitLowLimitThreshold` 要不要上屏（带 m/s→km/h 单位换算）。
环境类：`params.cc` 用 `-O1 -g0` 的峰值 RSS 实测（现在钉的是 -O0，261 MB/34 s）。
