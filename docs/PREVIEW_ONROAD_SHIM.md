# 行驶预览（Onroad Preview）里的 jetlink：`preview_shimd`

> 适用范围：本 fork（`sp-macanlong-test`）的「行驶预览 / Onroad Preview」功能，以及
> 「在停车预览里让 jetlink 大模型像正常点火一样接管」这件事。
> 相关：`ai/docs/JETLINK_WIFI_HANDSHAKE_ACCEPTANCE_1011.md`（Wi-Fi 链路上车验收）、
> `ai/docs/SIM_PREFLIGHT_STARTUP_CHAINS.md`（仿真前置门槛）、`ai/docs/GIT_PUSH_WORKFLOW.md`（推送流程）。

## 0. 一句话结论

「行驶预览」（`IsOnroadPreview`，Settings → Device → *Render the onroad UI while offroad*）原本只有摄像头画面：
轨迹画不出来，jetlink 大模型也永远换不进来。两者是**同一件事的两半**——预览里那几条 onroad
消息根本不存在。唯一**不碰 CAN、不写任何参数**的修法，是新增一个离路只读进程 `preview_shimd`
（`openpilot/sunnypilot/onroad_preview_shim.py`），替离路缺席的四个发布者发布四条消息。

**只画逗号本机模型的那些改法（A 类）解决不了 jetlink**：预览里 `card`/`selfdrived`/`controlsd` 全部
`only_onroad`，没有 `carControl` 帧，adapter 的 `in_control()` 恒为 True，大模型永远停在
`ready, waiting for a window to swap`。

## 1. 三道闸

| 闸 | 代码 | 改前 | 现在 |
|---|---|---|---|
| ① modeld 在预览里起不起 | `system/manager/process_config.py:270` `and_(or_(only_onroad, onroad_preview), is_stock_model)` | 开（本机 `ModelRunnerTypeCache=2` stock），但**起得来、发不出**：modeld 卡在 `params.get("CarParams", block=True)`，而 `CarParams` 是 `CLEAR_ON_MANAGER_START`、只有 `card` 写，离路永远不来 | 开，并且真发 `modelV2`（`selfdrive/modeld/modeld.py:258 car_params()`：预览且 `CarParams` 缺席时改读 `CarParamsPersistent`，只读） |
| ② 轨迹画不画得上 | `selfdrive/ui/onroad/model_renderer.py:93`：`extrinsicsCalibration` 与 `modelV2` 的 `recv_frame` 都要 ≥ `started_frame`（`selfdrive/ui/ui_state.py:220`，进预览那一刻取） | 没有 `extrinsicsCalibration`——只有 `calibrationd`(`process_config.py:286`)/`imu_calibrationd` 发，两个都是 `only_onroad` → 只画摄像头 | 闭合：shim 供校准，modeld 供 `modelV2` |
| ③ jetlink 换不换得进来 | `sunnypilot/jetlink_adapter/__init__.py:372 in_control()`（读 `carState`/`carControl`/`carControlSP`）→ `jetlink_repo/jetlink/openpilot/joining.py:367 _maybe_swap()`（要 `in_control=False` 且 `_small_frames >= 3`） | 预览里 `card`(:291)/`selfdrived`(:290)/`controlsd`(:288) 全 `only_onroad` → 没有 `carControl` → `in_control()` 恒 True → **一次都不换** | 闭合：shim 100 Hz 发这三条且 disengaged → `in_control()` 第一次为 False |

预览里换没换上**看得出来**：`selfdrive/ui/sunnypilot/ui_state.py:122` 的
`running_big = sm["modelV2"].big`，进预览后大模型图标会自己从 `joining → ready → running`。

## 2. shim 发什么（就四条）

| 服务 | 频率 | 内容 | 谁读 |
|---|---|---|---|
| `carState` | 100 Hz | 停着：`vEgo=0`、`standstill=True`、`valid=True`、**`canValid` 保持默认 False** | adapter 的 `in_control()`、HUD 速度 |
| `carControl` | 100 Hz | `enabled/latActive/longActive = False` | `in_control()` |
| `carControlSP` | 100 Hz | `mads.enabled/active = False`（MADS 也算 in control） | `in_control()` |
| `extrinsicsCalibration` | 4 Hz（每 25 帧） | 从 `CalibrationParams` 合成：`rpyCalib`/`rpyCalibSpread`/`wideFromDeviceEuler`/`height`/`validBlocks` + `calStatus`/`calPerc` | UI 渲染器（只读 `height`）、modeld（`rpyCalib`/`height`） |

速率是按服务自己的频率定的：三条控制路径是 100 Hz 服务（SubMaster 对 100 Hz 服务按 10/频率 秒判死），
校准是 4 Hz 服务并且只要"最新值"，所以每 25 帧发一次。

## 3. 只读证明（为什么不起 calibrationd / 不重跑指纹）

- **`CalibrationParams` 只 get，不 put。** `calibrationd` 是 `param_put=True`
  （`calibrationd.py:271`），每几秒 `params.put("CalibrationParams", ...)`（`:170-171`），
  spread 过大时还会 `reset` 回上一 block——预览里跑它就等于把车真正在用的校准交给一份离路数据去改写。
  shim 读同一个 key 合成 `extrinsicsCalibration`，一个字节都不回写。
  测试 `test_reading_the_calibration_writes_nothing` 用 `mock.Mock(spec=['get'])` 钉死这一点：
  对 store 的任何其它调用都会直接报错。
- **不起 `card`**：`card` 会重做指纹识别并写 `CarParams`。预览只需要 carState 这个形状，
  不需要"真车"，所以指纹这一步不做。
- **modeld 的 `CarParams` 回退也是只读**：`CarParamsPersistent` 是车自己上一次的指纹
  （`card` 复制到 `CarParamsPrevRoute` 用的同一份）。设备实测：预览跑完 `CarParams` 仍未被设置。
- 备份：B′ 方案实施前已把校准快照留在盘上（`ai/backups/CalibrationParams.bak-20261013`，
  sha256 `93251f93...a46a`，已 gitignore，不外传）。

## 4. 承重不变量：`valid=True`，`canValid=False`

`valid` 是预览自己的读者需要的（一条从没收到过的服务在 SubMaster 眼里是死的，`in_control()` 就永远不开）；
`canValid` 是**另一个**声明——它是车的 CAN 健康度，也是树里**所有写者**的闸门：

| 谁 | 位置 | 与 `canValid` 的关系 |
|---|---|---|
| `carrot_bluetooth`（`always_run`） | `sunnypilot/carrot/bluetooth/daemon.py:144` | `car_ok = alive && valid && canValid`；`car_ok` False → `hold_blocked` 分支，命令路径关闭。**这是离路唯一常驻读 `carState` 的写者**，也是这条不变量真正的理由 |
| `card` / `controlsd` / `selfdrived` | `card.py:328/348/366`、`controlsd.py:239/270`、`selfdrived.py:305/456/580` | 各自写 CAN / 写 `CarParams` 前都看 `CS.canValid`，而且全部 `only_onroad` |
| `locationd` / `calibrationd` / `torqued` / `paramsd` / `lagd` | `process_config.py:284/286/287/296/297` | 全部 `only_onroad`，预览里根本不跑 |

所以这一帧说的是"一台 CAN 不在的车"——离路停着时这就是事实。一条"更像真车"的帧（把 `canValid` 设上）
会悄悄把 `carrot_bluetooth` 的命令路径在离路打开，测试
`test_carrot_bluetooths_command_gate_stays_shut` 用 daemon 自己那条表达式钉住了这一点。

## 5. 离路消费者审计

| 消费者 | 位置 | 读到什么 | 判定 |
|---|---|---|---|
| `carrot_bluetooth` | `carrot/bluetooth/daemon.py:144` | `car_ok`（见上） | **承重，已钉**。`canValid` False → 命令不落盘 |
| 自动更新重启 | `carrot/server/services/auto_update.py:89 AutoRebootCondition` | PARK 模式要 `selfdrive_valid`，而离路没有 `selfdriveState` → 不成立；DISENGAGED 模式本来就认 `offroad`（`deviceState`），shim 之前就成立 | 无变化 |
| athena 远端 bridge | `system/athena/athenad.py:855` `bridge_services_out=["carState","deviceState"]` | 只在用户/athena 主动开的 WebRTC bridge 会话里把 `carState` 转给远端 | 转的是"真的停着"，显示层 |
| carrot web（live_runtime / snapshot / raw_services） | `sunnypilot/carrot/server/...` | 仪表盘显示 parked 值 | 显示层 |
| `carrot_man`（`always_run`） | `carrot_man.py:1471/1620`、UDP 7705 广播 | `v_ego_kph=0`、`v_cruise_kph=0`、`logCarrot` | 显示层，值是停车的真值 |
| `xiaoge_data` | `sunnypilot/carrot/xiaoge_data.py:255` | `alive` 即广播 parked `carState` | 显示层（`CarrotEnabled` 才起） |
| 仪表 overlay | `sunnypilot/carrot/cluster_view/cluster_overlay.py:100` | 速度 0 kph | 正确（车确实停着） |
| UI onroad 面板 | `selfdrive/ui/onroad/hud_renderer.py:107`、`selfdrive/ui/sunnypilot/onroad/*` | 都先比 `started_frame`，值取 0 / `standstill=True` | 与"停着"一致；组合读取（`mici/layouts/onroad_info_panel.py:119`）还要求 `controlsState` 有效，离路没有 |
| `drive_stats` | `selfdrive/ui/sunnypilot/lib/drive_stats.py:59` | 读的是 route log，不是实时总线 | 无关 |

结论：**不需要给任何消费者加排除逻辑**；唯一需要"钉住"的是第 4 节那条 `canValid` 不变量。

## 6. 设备侧验收步骤

1. 设置 → Device → 打开 **行驶预览**（离路、`IsOnroadPreview=1`）。
2. 轨迹：进预览约 15 s 后 `modelV2` 开始来（模型加载），随后约 13 Hz；`extrinsicsCalibration` 4 Hz。
   屏幕上应当出现 path / 车道线。
3. jetlink 大模型：看右下/状态处的大模型图标是否 `ready → running`，或
   `grep -E "jetlink:|large model joined mid-drive|built the large model state" /data/log/latest.log`；
   看到 `jetlink: large model joined mid-drive, modelV2.big is now true` 就是换上了
   （`joining.py:353`）；只看到 `jetlink: link ready, waiting for a window to swap`（`:546`）说明窗口没开。
4. 只读复核：`params.get("CarParams")` 预览前后都应为未设置；`CalibrationParams` 的 mtime/内容不变。
5. 收尾：关掉预览，或点火进入真实 onroad —— gate 是
   `IsOnroadPreview and not started`（`process_config.py:113`），shim 立即退出，真实发布者接手。

## 7. 前提与边界（别踩）

- **Jetson 在点火轨上，车不点火它没电**，boot 45–100 s，没得换。所以要"停车预览里跑大模型"，
  host 得是**自带电**的（Mac / iPhone，`JetlinkLink=3` = wifi 就是这条路）；host 若是 Jetson，
  则必须点火，而点火后 comma 会 onroad、预览被真实 onroad 界面顶掉 —— 这个用法不成立。
- **预览里速度恒为 0**：`carState` 是"停着的"合成值。想要真实速度/挡位就得起 `card` 级别的东西，
  会重跑 `CarParams` 指纹 —— 这是当初选 shim 而不是起 `card` 的原因，**不做**。
- warp 必须先在设备上 build：`openpilot/sunnypilot/jetlink_adapter/models/warp_1928x1208_512x256_tinygrad.pkl`。
- 预览里**绝不会有**任何控制输出：`selfdrived`/`controlsd` 保持离路，shim 不发布 `sendcan`/`controlsState`/`selfdriveState`/`carParams`。

## 8. 文件与提交

- `openpilot/sunnypilot/onroad_preview_shim.py` —— shim 本体（离路只读）
- `openpilot/system/manager/process_config.py` —— `onroad_preview_shim()` gate(:113) + `preview_shimd`(:275)
- `openpilot/selfdrive/modeld/modeld.py` —— `car_params()` 的只读回退(:258)
- `openpilot/sunnypilot/tests/test_onroad_preview_shim.py` —— 17 例：`in_control()` 契约、真实收发、
  校准往返、只读证明、gate 真值表、`canValid` 不变量
- 提交：`d7716b7b2f`（shim 本体）、`97591f674a`（校准只序列化一次）、
  `217bb148ca`（modeld 不再等 `CarParams`）、`8a94f8be01`（ai 指针）
