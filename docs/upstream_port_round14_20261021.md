# 上游搬运 第 14 轮（2026-10-21）

基线：本树 `sync/upstream-1019`，起点 `2e5febde91`（round 13 收口），终点 **`8f7d558c70`**。
上一轮把 `927498237f`（modeldLagging 两档）搬完时，`upstream/test` 停在 `1952394252`。

## 1. 上游增量扫描

`git fetch upstream test`：`1952394252 → 4993c3cf32`，**27 个提交**，全部在 `openpilot/` 子树，
外加 3 次 webui 子模块指针。按体积分三类：

| 类 | 提交 | 说明 |
|---|---|---|
| 真功能 | `50cf6414ba` Safe Mode 入口（412 行）· `e428c9535a` 调参层级声明（283 行）· `9b47b4da32` modes 单一闸门（143 行）· `3255c6a75b` Open-Meteo 天气（560 行）· `1e98e8d56b` WeatherState 轮询（158 行）· `181f6be737` 天气六行 UI（127 行）· `bda1e2bb27` 心跳清扫（120 行）· `30d3ea39ed` modeld 分阶段计时（49 行） | 全部搬 |
| 修 bug / 契约 | `4b98f11d59` 五个跟车档位存不进去（+ 缩放契约测试）· `4993c3cf32` 自动探测默认值读错 · `2df5ff11e3` Safe Mode 写入类型 · `8ba37f6600` 读回归一 · `047ad36feb` level-1 变规则 | 全部搬 |
| 删死代码 / lint / 测试 | `6c2db88b86` 删 credentials 草稿（-230 行）· `41d7c12481` 删 carrot_catalog（-122 行）· `e12ae265f6` import 守卫 · `c3926e3885`/`dd91852db6` mode 端点测试隔离 · `0a0913f343`/`2a8bd05780` lint | 全部搬 |
| 不搬 | `0facf5cf71` agnos 刷机包地址换腾讯 cnb | 见 §5 |

## 2. 本树提交

| 本树 | 上游 | 内容 |
|---|---|---|
| `57b7474286` | `bda1e2bb27` `30d3ea39ed` `c3926e3885` `dd91852db6` | 心跳文件清扫 + modeld 分阶段 p50/p99 + mode 端点测试不再泄漏状态 |
| `feefceb48a` | `50cf6414ba` `2df5ff11e3` `8ba37f6600` `2a8bd05780` | Safe Mode 有了入口：`safe_mode_runtime` 的 enter/restore/status、`SafeModeError(status)`、Device 页按钮 |
| `666bce23b7` | `9b47b4da32` | modes：三个写实验模式的地方合成一个闸门 |
| `050063f37c` | `e428c9535a` `047ad36feb` `0a0913f343` `0a976b1c6f` `fbd6643788` `72c6200b79` `41d7c12481` `6c2db88b86` `e12ae265f6` | 调参层级声明 + 目录读取 + level-1 规则 + 两个死代码删除 + import 守卫 |
| `8f7d558c70` | `3255c6a75b` `1e98e8d56b` `181f6be737` `4993c3cf32` `4b98f11d59` `e2f98365d6` `1952394252` `58f7e56e89` | 天气自适应（探测 + 状态 + 六行 UI）+ 跟车档位 INT 修正 + webui bump |

## 3. 抓到的真问题

**① Safe Mode 以前只有「规则」没有「入口」，而且写入是坏的。**
`Params.put` 对 BOOL/INT/FLOAT/JSON/BYTES 键拒绝 `str`，抛 `TypeError` 而 `_put` 吞掉了 —— 唯一活下来的写操作是
`remove()`。也就是说 Safe Mode 会**删掉**转向类旋钮、却记不下它们原值，恢复时静默什么都不做。
上游 `2df5ff11e3` 的 `_coerce` 按注册类型转换后修好；`8ba37f6600` 再把读回方向也归一（`str(dict)` 不是 JSON，
`json.loads` 必失败）。合并时 `safe_mode_runtime.py` 三处冲突全取上游：本机旧版 `_coerce` 与上游同义但签名不同，
留两套只会让下一次 rebase 再撞。

**② `level-1 必须有 UI 入口` 这条规则，正好是这套 feature_support 的消费者。**
`audit_ui_reach.level_one_gaps()` 现在会让「声明成日常、却只能 curl 打开」的键直接测失败。本机重生成
`docs/carrot_no_ui_switches.md`：**23 个可达 / 1 个不可达**（`VisionSpeedLimitLowLimitThreshold`，阈值，脚本面），
表里每个 level-1 键都有控件。

**③ `DynamicTFollowLC` 声明成 FLOAT，行控件是整数百分比 —— 这一档永远存不进去。**
整数控件写 FLOAT 键抛 `TypeMismatch`；唯一会写浮点的控件 `use_float_scaling` 会先除 100，于是存成 `1.00`，
而消费者要的是 `100`。改成 INT（同 `TFollowGap*` 的表示），并新增 `test_float_scaling_contract.py` 把规则钉住，
下一个同类行不可能再悄悄发出去。

**④ 天气那套以前是「搬完了但什么都不发生」。**
`weather_offsets.py` 早就在（`7795423183`），但没人生产 `WeatherState`。这轮补上 Open-Meteo 探测：
定位过期 / 请求失败 / WMO 码不认识，一律返回 unknown，**不猜** —— 猜错一次「下雨」就会静默加跟车时距。
另外 `4993c3cf32` 修的是「未设置的自动探测键按声明默认（ON）读」，之前当 OFF，新设备永远探测不到。

**⑤ 本机自己引入的缺译，被上游的渲染冒烟测试抓出来。**
round 12 加的 Developer 页 22 条标题（`Lead Preview` / `Gap Recovery` / `Traffic Light Fusion` …）从来没有中文，
`carrot_tuning_render_smoke.py` 报 `zh-CHS missing: [...]`。已补 zh-CHS + zh-CHT，194/194 根页字符串全绿。

## 4. 合并冲突（都出在本机分叉处，逐条记录）

| 文件 | 冲突 | 解决 |
|---|---|---|
| `common/params_keys.h` | 三段：`CarrotEnabled` 附近块 / `TrafficLightDetectMode` 附近块 / `CarrotSourceTimeoutMs` 附近块；另有 `DynamicTFollowLC` 类型 | 上游元数据（`std::nullopt, level, tier`）照收，本机独有键保留：`AutoNaviRearCameraHoldDistance`、`LeadAccelResponseTF1-4`、`ATCMaxSpeedKph`、`CarrotCurveSpeedEnabled`、`CarrotHudInfoEnabled`（这些保持 level 0，避免给没有控件的键声明「日常」） |
| `tests/audit_ui_reach.py` | 本机有 `_NO_UI_NOTE` / `_ALL_REACHED_NOTE` 与 curl 示例，上游加了 `_level_line()` | 两者都留：本地注释 + `_level_line` + `_head(levels)` 签名 |
| `tests/test_carrot_ui_reach.py` | 上游新增 `test_no_everyday_knob_is_left_without_a_control` | 照收，并补 `level_one_gaps` 的 import（上游那条 diff 本体没带进来，手工补） |
| `tests/test_settings_catalog_metadata.py` | 上游新文件 + 本机已删 `carrot_catalog()` | 断言改成「与服务出来的 catalog 逐键对比」（`self._by_name()`），不引已删函数；上游删掉的 `None` 用例照收 |
| `docs/carrot_no_ui_switches.md` | 本机 23 行有 UI，上游 5 行 | 不手合，`audit_ui_reach.py --write` 重新生成 |
| `sunnypilot/selfdrive/car/interfaces.py` | 上游加 `seed_mazda_torque_defaults` 调用与注释 | 取上游；顺带发现 `manager.py` 只 import 了 `seed_car_defaults_offroad` 却没调用，补回调用（离线种车默认值以前从未跑过） |
| `translations/app_zh-CHS.po` / `CHT` | 上游在文件尾追加天气六行的译文 | 取上游，再手工追加本机缺的 22 条 |
| webui 子模块 | 本机领先（含 CustomSR 行），上游 `0ec403f435 → 599fdd0` 两个提交 | 先在 webui 里把 CustomSR 行落成 `f238b31`（并**保持 CRLF**，上一次改成 LF 让整文件冲突 4217 行），再 merge；`test_panel_catalog.py` 冲突保留本机 `_find_config_py()` + 取上游 `not_tuning_keys`（天气三键不算调参键） |

## 5. 明确不搬

`0facf5cf71`「boot/system 系统包换腾讯 cnb 地址」：只改 `common/hardware/comma/agnos*.json` 的下载 URL，
是 comma 设备刷机包来源。本机是 SM6450 自研机型，不走 agnos 刷机路径；搬了不生效，还会在以后 rebase 时
把上游 URL 覆盖成第三方镜像。登记表里标 `skip`，探针 `symbol_absent: cnb.cool`。

## 6. 验证与实测

- `libparams_c.so` **已重建**：`scons -j1 openpilot/common/libparams_c.so`，offroad、`nice`，`common/SConscript`
  仍钉 `-O0`，未触发 lowmemorykiller。不重建的话新声明读不到 —— `CarrotEnabled` 会报 level 0、
  目录元数据断言直接失败（这一条是先在设备上撞到才发现的）。
- 单测：`sunnypilot/common/tests` **181 passed**；`test_settings_catalog_metadata` + `test_carrot_ui_reach` **20 passed**；
  `test_relative_imports_resolve` + `test_float_scaling_contract` + `test_weather` + `test_watchdog` + `test_carrot_server_params`
  全绿（`test_carrot_server_params` 29 passed，跑两遍一致）。
- 渲染/字体：`carrot_tuning_render_smoke.py` **21/21**；`font_fallback_coverage.py` **248/248**。
- `audit_param_consistency.py`：4 条 FAILED 与改动前一致（`StarPilotTogglesUpdated` 未注册、cabana 两个 UI 键、
  Onnx* 五个键只在原生 UI 可见），本轮没有新增。
- ruff：改动文件里只剩既有的 `ISC002`/`E501`/`F841`；顺手清掉 5 条能清的死 import（`carrot_tuning_items` 的
  `Params`/`LineSeparatorSP`/`button_item_sp`、`audit_param_consistency` 的 `glob`、`modeld.py` 重复 import）。
- 既有失败（与本轮无关，逐条核对过）：`system/tests/test_logmessaged.py::test_big_log`（msgq 环境）、
  `system/manager/test/test_restarting_process.py` 的 AudioProcess 类型断言、`settings_panels_render_smoke` 的
  Device(`always_offroad` 假 ui_state) 与 sunnylink 两条。

## 7. 待办（下次上路前）

1. **重启后才生效**：新 `libparams_c.so` 已落盘，在跑的进程还映射着旧库。新键默认 0/关，所以不急重启，但
   Safe Mode 按钮、天气六行、调参层级上屏都要在**重启 + offroad** 之后才算验过。
2. Safe Mode 端到端：进/出一次（只删转向类键、备份 JSON 能读回），确认车上行为与 `safe_mode.py` 规则一致。
3. 天气：`WeatherAutoDetect` 默认 ON（声明如此），实际会打 Open-Meteo。需要确认车机有网时返回、断网时保持 unknown
   而不是 0 偏移；`WeatherState` 进 `params_bulk` 也能看到。
4. `DynamicTFollowLC` 从 FLOAT 改 INT：如果车上还留着旧的 float 值，读 INT 可能不匹配 —— 首次启动后看一次
   `params_bulk`，必要时删键回默认。
5. `-O1 -g0` 峰值实测（第 14 条 todo 仍在）：`-O0` 是保守钉法，实测过了再决定是否升级。
6. 上游只剩 `63a6f3211b`（NNFF 127 文件 + 模型资产）没搬，属体积/驾驶决策项。
