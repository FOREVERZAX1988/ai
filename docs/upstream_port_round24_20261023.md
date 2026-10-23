# 上游复查 + divergence 登记 — round 24（2026-10-23）

> 树：`/data/openpilot` 分支 `sp-macan-test3`
> 上游：`upstream = mouxangithub/openpilot`，`upstream/test`（TRAP 仍在：只读 `refs/remotes/upstream/test`，
> 并用 `git ls-remote upstream refs/heads/test` 复核；`refs/remotes/mouxan/test` 是孤儿引用）
> 机器可读登记：`ai/docs/upstream_divergence_registry.json`
> 检查器：`python3 ai/scripts/upstream_divergence_check.py --ref upstream/test --side worktree`

## 0. TL;DR

| 事 | 结论 |
|---|---|
| `b660e1416c` cherry-pick | **已落地** `46b709561b`（零冲突，父仓文件与上游 parent 逐字节一致），新增 3 条测试全绿 |
| 上游有没有新东西 | **有**：`8e51f886d9` → `1e97bf13a9`，**新增 7 条**（10-23 15:04–15:37，全部 wheel_controls / xiaoge / capnp 测试方向） |
| 「上游 11 条」登记 | **已登记**（第 2 节表 + registry `items`/`unported_unprobed`），以后不会再被当成本地回归重开 |
| 上游同源红 | **4 条**（第 4 节），含原登记 2 条 + 本轮实测新增 2 条 |
| 顺手挖出的 P0 | **2 个**（第 5 节）：① `control+sd` 读了已被上游改名的 `UsbGpu*` 键；② 重排把 fork 的 **51 个 params 键**整段抹掉，Macan 坡度补偿/雷达融合/起步跟停全部静默失效 → 已恢复并重建 `libparams_c.so`（验证 731 键） |

## 1. 上游 tip 变化

```
git ls-remote upstream refs/heads/test   ->  1e97bf13a9
git log --oneline 8e51f886d9..upstream/test
1e97bf13a9 test(capnp): pin blindspot split fields at @75-79 after ordinal-hole fix
1c162bcae3 fix(mpc): jerk_channels import path - module lives under sunnypilot/, not selfdrive/
ee23033248 更新（AGENTS-memory + opendbc 指针）
5af396b880 test(wheel_controls): make unknown-keycode fallback independent of the optional inputs package
67ffbe9f03 xiaoge: adopt cp's three-class BSD classifier with dual-side continuous monitoring
29bfad171c fix(build): repair SConstruct syntax - except clause merged onto the try body line
ad617598df feat(wheel_controls): generic USB/BT input layer - zero new params, zero compiled artifacts
```

## 2. 「上游 11 条」登记（截至 8e51f886d9 未移植）

`git cherry HEAD upstream/test` 在 8e51f886d9 那一刻刚好 11 条：

| # | commit | 主题 | 判定 | 下一步 |
|---|---|---|---|---|
| 1 | `564e8e93c8` | merge: test → zoompilot develop（1687 文件） | 上游自己的 rebase 基座，不逐条搬 | docs |
| 2 | `29174dca73` | speed_limit/mpc/dec：tiered offsets、三通道 jerk、DEC 触发、方向确认（20 文件 +1351） | **eval**：动纵向与 MPC | 路试后单独一轮；先只搬 `tiered_offset.py`（默认关） |
| 3 | `2fe4acf5dc` | carrot：cp P0-P2 批（UI 诊断 / 滑行门控 / cereal 字段 / web 限流，38 文件 +1814） | **eval**：跨 UI+控制+cereal | 逐文件评估，不能整批 |
| 4 | `fa32bf598b` | vasm/signal：BSD 刷新竞态、开关清理、观测字节缓存 | todo-after（依赖 #3） | 跟 #3 同批 |
| 5 | `2dc4d8de39` | 巡航接通时的 e2e 静止提示音（E2EAlertsWhenEngaged） | todo（10 文件，含 settings_ui.json 三处） | 可搬 |
| 6 | `7ed16d83a6` | xiaoge：YOLO 障碍物头（新增 `yolo_inference.py` 345 行 + M1-M3） | **eval**：体积大 + 要模型资产 | 等驾驶者决定要不要 |
| 7 | `b660e1416c` | speed_limit_vision 只订阅本 fork 真有的服务 | **已搬**（`46b709561b`） | — |
| 8 | `f1751249ae` | xiaoge：两份 YOLO 检测器为何并存（纯注释） | docs | 随 #6 |
| 9 | `9410aec458` | 上游 `AGENTS-memory.md` +28 行 | docs（上游内部记忆体系，与我们的 `ai/` 不同） | 不搬 |
| 10 | `2e60e286ac` | carrot：可执行收藏槽（setting_favorites 一键切换/循环/取值 + 新测试） | todo（纯服务层，零控制链） | 可与 #11 同批 |
| 11 | `8e51f886d9` | carrot：`/api/system_monitor` 只读进程/CPU 快照 + 169 行测试 | todo（只读接口） | 可搬，最便宜的一条 |

registry 里这 6 条（#2/#5/#6/#10/#11 + #4 的测试）已经写成**可机器判定的 `path_absent` 探针**；
剩下 5 条（`2fe4acf5dc` `fa32bf598b` `2dc4d8de39` `f1751249ae` `67ffbe9f03` `29bfad171c` `1c162bcae3` `1e97bf13a9` `ee23033248` `9410aec458` `564e8e93c8`）
放在 `upstream_pending_port.unported_unprobed`，**故意不写探针**（避免假装绿）。

## 3. 新增 7 条的判定

| commit | 判定 | 理由 |
|---|---|---|
| `ad617598df` wheel_controls 通用 USB/BT 输入层（+1433 行，注册进 process_config） | **eval** | Macan 原厂按键走 CAN，不需要这一层；且会动 manager 进程表，路试前不动 |
| `67ffbe9f03` xiaoge 三分类 BSD 分类器 + 双侧连续监控 | **eval** | 540 行、与盲区语义相关，需驾驶者决定 |
| `5af396b880` wheel_controls 测试与可选 inputs 包解耦 | todo-after（依赖 `ad617598df`） | — |
| `29bfad171c` SConstruct 语法修复（except 并进 try 行） | todo | 先确认本树 SConstruct 是否同一份 |
| `1c162bcae3` MPC `jerk_channels` import 路径修正 | todo | 一行，与本树 `long_mpc.py` 分叉相关，路试后核对 |
| `1e97bf13a9` capnp 盲区拆分字段 @75-79 断言 | eval | 本树 capnp 已上游化，先确认字段号已成立 |
| `ee23033248` 上游记忆文档 + opendbc 指针 | pointer | 指针需单独确认 |

## 4. 上游同源红（不要当本地回归重开）

判据：涉及文件与 `upstream/test` 逐字节一致，或用上游同一份源码跑同一断言同样红。已写进 registry 顶层 `upstream_same_red`。

| # | 用例 | 现象 | 为什么是上游的事 |
|---|---|---|---|
| 1 | `selfdrive/controls/tests/test_longcontrol.py::TestStoppingHold::test_stopping_decel_rate_is_smooth_while_rolling` | `assert 0.07 == 0.3` | 上游断言 0.3，而同一提交里的 `numpy.interp` 曲线给 0.07——上游自相矛盾。本树该文件与上游逐字节一致（`2e36dcdd71` 时就是这样），1 failed / 18 passed 一直是这一条 |
| 2 | `common/tests/test_absolute_imports.py::AbsoluteImportRootTests::test_every_absolute_import_has_a_published_root` | 3 处 `from cereal import ...`：`sunnypilot/system/speed_limit_vision.py:374`、`sunnypilot/selfdrive/ui/beepd.py:8`、`selfdrive/controls/tests/test_lead_data_field_map.py:16` | 三份文件 `git diff upstream/test` 为空；本仓只有 `openpilot.cereal`、没有顶层 `cereal`。**连带后果**：`beepd`（Lite 蜂鸣器）与 `speed_limit_vision` 的 `use_runtime` 分支在设备上 import 即失败——这是上游缺陷，不是我们搬坏的 |
| 3 | `sunnypilot/carrot/server/tests/test_auto_update.py::test_git_pull_reports_actual_update_and_records_pull_time` | `AttributeError: ... has no attribute '_notify_cwp'` | 上游 test 引用 `_notify_cwp`，**上游自己的** `auto_update.py` 也没有（test=1 处 / service=0 处）。24 条里就红这一条 |
| 4 | `common/tests/test_watchdog.py`（重启窗口） | `struct.error: 'Q' format requires 0 <= number <= ...` | 上游把 heartbeat 往前记 3600 s，`CLOCK_BOOTTIME` 从开机算，uptime<1h 时为负。**uptime>1h 时 19 条全绿**——看到这条先看 uptime |

## 5. 本轮实修（都带验证）

### 5.1 `b660e1416c` cherry-pick → `46b709561b`
- 上游 parent 版 `speed_limit_vision.py` 与本树**逐字节一致**，所以零冲突。
- 效果：不再订阅本 fork 没有的 `mapdOut` / `livePose`（`SubMaster.__init__` 里 KeyError 会让 daemon 一启用就死）；地图上下文改读 mem-params 的 `MapSpeedLimit` / `NextMapSpeedLimit` / `RoadName`；`live_pose_inputs_ok` 恒 True（没有 pose 源就不能声称 pose 坏了）。
- 新测试 `sunnypilot/system/tests/test_speed_limit_vision_services.py`：3 passed（静态读源码 + 比对 `cereal.services.SERVICE_LIST`）。

### 5.2 P0-①：`control+sd` 读的是已被上游改名的 `UsbGpu*` 键
- 上游 `5cfdb2f4da rename usbgpu to chestnut` 把 `UsbGpuActive/Loading` 改成 `ChestnutActive/Loading`（本树 `params_keys.h` 已注册 Chestnut*，`UsbGpu*` 不存在）。
- 真机验证：`Params().get_bool('UsbGpuLoading')` → **`UnknownKeyName`**。而 `selfdrived.update_events()` 每帧都读它 → 一上路就抛异常。
- 修：`selfdrived.py` 两处改读 `Chestnut*`（局部变量同步改名）；`webui/server/bridge/{models_api,state_api}.py` 同改（JSON 字段名不动，只改键名）。
- `signal_neural_shadow.automatic_backend()` 同样问题 + `DriverMonitoringSessionDisabled` 从未注册 → 四个键全部改走 `param_read.read_bool`，GPU 键读 `ChestnutActive`。
- 验证：真机 `automatic_backend(Params())` → `tracking_cpu`，不抛异常；`test_signal_neural_shadow.py` **6 passed**。

### 5.3 P0-②：重排把 fork 的 51 个 params 键整段抹掉（最严重）
- `7399ffe498 port(round 23)` 以 `9e002fb2dc` 为底重排，把 `common/params_keys.h` 换成了上游那份 → fork 自有的 **Macan\* / UseKonikServer / DpEps\* / Carrot\* 共 49 个键 + CarSelected3 / ScreenRecord 共 51 个键全部消失**。
- 后果（真机实测 `UnknownKeyName`）：opendbc `carcontroller/carstate` 里 `MacanSlopeComp / MacanRadarFusion / MacanStartupGapSync` 等**被 try/except 兜成 False** → 车能开，但**坡度补偿、雷达融合、起步跟停、距离档同步全部静默关闭**；UI 的 Macan 面板与 mads 起步跟停（无兜底）则直接抛异常。
- 修：把这些注册行按原样恢复进 `params_keys.h`（带「must survive every upstream merge」注释 + 一段说明为什么不恢复 `UsbGpu*`），`scons -j1 openpilot/common/libparams_c.so` 重建（2 m 31 s，无 LMK）。
- 验证：键数 **680 → 731**；`MacanStartStop=True` / `MacanRadarFusion=True` / `MacanStartStopDistance=5` / `CarSelected3='MOCK'` 都读得出来（说明驾驶者原来的设置还在，没有丢）；未知键仍然抛 `UnknownKeyName`（校验没被削弱）。
- 回归：`common/tests` + `sunnypilot/common/tests` + `test_state_machine` + 上面两个新测试 = **262 passed / 258 subtests**，唯一红是第 4 节 #2 的上游同源红。

### 5.4 registry 与检查器对齐
- `0facf5cf71`（agnos cnb 地址）、`0d9ec846db`（jetlink cross-fork API）两条探针已经 DRIFT → 移进 `resolved`。
- `test_auto_update.py` / `fleet_safety.py` / `test_watchdog.py` / `test_longcontrol.py` / 新增 `test_absolute_imports.py`：`expect_diff` 按实测改成 False 并加 `upstream_same_red` 标记，phase 1 不再误报 WARN。
- `signal_neural_shadow.py` 的 `upstream_intent_present` 改成 `read_bool` + `ChestnutActive` 版本。
- 推迟钩子 `44a32ec77c`（learned-vs-user 横向仲裁）探针显示符号已在 → status 翻 `ported`。
- 现在：**phase 0 OK；phase 2 8/8；phase 3 4/4；phase 1 = 24/31 as expected**（余下 2 FAIL + 4 WARN 见第 6 节，都是真欠账，没有假装绿）。

## 6. 仍未处理（按危险度排序）

| 级别 | 项 | 说明 |
|---|---|---|
| 中 | `dmonitoringd.py` 分叉被抹平（WARN） | 本树现在与上游逐字节一致：上游两支都要求 `DM.always_on`，我们原本两支都不要求。registry 里本来就是 `pending-ab`（等驾驶者 A/B），所以先记录不擅自改 |
| 中 | `jetlink_adapter/__init__.py`（FAIL） | 上游 `hevc_venus` HEVC 编码接线不在本树文件里。没有它走的是原有编码路径，不影响今晚路试，但要决定是搬还是明确拒绝 |
| 低 | `sunnylink`/`test_signal_assist_runtime.py`、`radard_dpath.py`（WARN） | 前者是测试与上游一致（我们那点差异没了，需确认是否要补回断言）；后者纯注释差异 |
| 低 | `test_longitudinal_planner.py`（FAIL） | 我们 `assert planner.source != LongitudinalPlanSource.carrot` 那条断言在重排中丢了，测试变弱 |
| — | 第 2/3 节的未移植清单 | 见 registry，不搬的都写了理由 |

## 7. 部署注意（今晚路试前必看）

1. **`params_keys.h` 改了 → `.so` 必须重建**（已重建）。python 侧按 `mtime+size` 用私有副本
   `/data/.cache/params_lib/libparams_c-<mtime>-<size>.so`，新进程自动用新的；**已在跑的进程仍持旧 mmap**。
2. 因此需要 `sudo systemctl restart comma`（只重启 carrot_server 不够：manager 自己抱着旧 mmap，子进程跟着旧库）。不做这一步的表现是**静默的**——新键在所有已跑进程里仍是 `UnknownKeyName`。
3. 重启后自检：
   ```
   PYTHONPATH=/data/openpilot /usr/local/venv/bin/python3 -c \
     "from openpilot.common.params import Params; p=Params(); print(len(p.all_keys()), p.check_key('MacanStartStop'))"
   # 期望 731 b'MacanStartStop'
   ```
4. 路试时如果出现「Macan 面板打开报错 / 起步跟停不生效 / 坡度补偿像没了」，先按第 3 条自检键数——这是本轮修的那个 P0 的复查点。
