# 上游移植 round 12（2026-10-23 夜）— A：逐条未移植表 + B：批 0/1 落地

> 上游 `mouxangithub/openpilot:test` tip = `684178cb51`（`git ls-remote` 与 `git rev-parse upstream/test` 交叉一致）
> → **上游没有我们还没拉的新提交**；`HEAD..upstream/test` 仍是 25 条，分解见 §1。

## 1. 25 条的账目（可机器复算）

| 类别 | 条数 | 判据 |
|---|---|---|
| 已等价落地 | 6 | 本轮逐条跑 `git show X \| git patch-id --stable` 与本地对应提交 **全部 PATCH-ID-EQUAL**：684178cb51→c0b3171e66、4c4c654fef→5567678adb、8a7e93181d→ba96418ec9、b82043d2a7→4c4e086183、b5061ca8c4→0d6fc24ea4、b660e1416c→46b709561b |
| 未移植 items | 19 | registry 逐条 path/symbol 探针全绿（`--pending-only` → `19/19 still unported`） |
| 合计 | 25 | 6 + 19 |

（`eeb028a58` 是 panda 子模块 pin，不在父仓差集里，单独一条 pointer item；`2e36dcdd71` 已证伪在 `merged_in`。）

## 2. 本轮落地的提交（父仓 8 + opendbc 1）

| 上游 | 本地 | 主题 | 验证 |
|---|---|---|---|
| 8e51f886d9 | 85f2fab905 | /api/system_monitor | 7 passed；设备实跑两次采样 cpuPercent 26.1 / 6 核 / mem 1692MiB / 571 进程 |
| 4ff945e764 | a7efcc5615 | test_carrot_man Params rebind | 159 passed |
| 2e60e286ac | 72378d540c | 可执行收藏槽位 | server 157 passed / 48 skipped |
| 2dc4d8de39 | dbf14ed4ae | E2E 驻停提示音 | test_e2e_alerts_helper 3 passed；params_metadata 6 passed |
| ad617598df | 5de73c5eb8 | wheel_controls 输入层 | ruff 全过（去掉未启用的 S310 noqa）；26 passed |
| 5af396b880 | b45d4872a9 | 未知键码 fallback | 27 passed（设备装了 inputs 包，正是本条要修的） |
| 2fe4acf5dc | 587cb39ebc | cp P0-P2 批（UI 诊断/coasting 门/字段/限流） | 13 passed；coasting veto 符号逐一在位 |
| 29bfad171c | 3c93ed9fb6 | 修 SConstruct 语法 | `compile(SConstruct)` 通过 |
| opendbc 8c12b1236 | opendbc b9e3f0060 | CarState @72-74 vCluRatio/speedLimitDistance/logCarrot | capnp compile rc=0；pycapnp 写入回读 ok |

opendbc 子模块冲突的处理：上游该批要求 pin 到 8c12b1236，但其父 `a3c88c85e`「适配c3」是 BYD+hyundai 大改，本 fork 无此 2 提交且已分叉 282 提交 → **只单独 cherry-pick 8c12b1236**，指针记为本 fork 合并提交 b9e3f0060；`a3c88c85e` 仍留 `ee23033248` 整批评估。

## 3. 构建

`scons -j4` 首次 `Error -9`（OOM，3.6G 内存跑 4 路 C++）；`scons -j2` → `done building targets`。
`libparams_c.so` 重建（strings 含 `OnnxBsdEnabled`）；`cereal/gen/cpp/car.capnp.h` 含 `getVCluRatio` / `SpeedLimitDistance` / `LogCarrot`。
（注：`carrot` 代码里 `from cereal import car` 在本树走不通，正确写法是 `from opendbc.car.structs import car` —— 与既有「上游同源红」的 absolute-import 条目同源。）

## 4. 仍未移植（12 条）

| 上游 | 状态 | 为什么还没搬 / 下一步 |
|---|---|---|
| 29174dca73 | eval | speed_limit tiered offset + MPC 三通道 jerk + DEC；动纵向/MPC，需手工 rebase（与本地 relc/stopping 分叉重叠，6 文件冲突面） |
| 1c162bcae3 | todo-after | 依赖 29174dca73 的 jerk_channels，随之 |
| 67ffbe9f03 | eval | cp 三类 BSD 分类器；7 文件冲突面（params_keys/card/config/v_asm_model.onnx） |
| fa32bf598b | todo-after | vasm BSD 刷新竞态，依赖 67ffbe9f03 |
| 7ed16d83a6 | eval | YOLO 障碍头；**本轮实测 2 文件硬冲突**（v_asm_server.py / test_xiaoge_onnx_lifecycle.py），需按本 fork 的 vasm 结构手工并 |
| f1751249ae | docs | 随手带上（一条 docstring），与 7ed16d83a6 同批 |
| 1e97bf13a9 | todo-after | capnp 契约守卫把 blindspot 钉 @75-79；字段由 67ffbe9f03 引入，**blocked_by 67ffbe9f03**（本树 CarState 现在到 @74） |
| eeb028a58 | pointer | panda c3 pin（eeb028a58a）不在本 fork panda@d84b110fc；两侧已分叉，整批评估 |
| ee23033248 / e3cf1856c9 | pointer | opendbc 指针含 `a3c88c85e` 适配c3 大改，整批评估 |
| 564e8e93c8 | no-port | 上游单亲 merge（1687 文件），永不整搬 |
| 9410aec458 | no-port | `AGENTS-memory.md` 已随 2fe4acf5dc 落地（文件在），条目标为 merged_in |

## 5. 既有红（本轮实测确认，非本轮引入）

- `test_auto_update.py::test_git_pull_reports_actual_update_and_records_pull_time`：`auto_update` 无 `_notify_cwp`（上游测试 pin 了上游 cwp 钩子）。
- `test_carrot_navi_no_aiohttp`（2 例）：子进程里 `ModuleNotFoundError: No module named 'openpilot'` —— 该用例文件本轮未动，是「subprocess 必须带 PYTHONPATH=/data/openpilot」的环境口径，与既有 absolute-import 同源红一族。
- `sunnylink test_settings_changes`：`settings_ui.json` 的 cruise>carrot_navigation 条目缺 key/widget；TorqueControlTune 仍带静态 options。**把 HEAD 版 json 抽到 /tmp 跑同一 validator 输出逐字符相同**。

### 本轮修掉的一条半移植红

`test_v_asm_parked_gate::StatusContractTest`（2 例）在 2fe4acf5dc 之后红：`VASMService` 新增 `bsd_enabled`，而测试 helper 绕过 `__init__` 造对象。运行期代码保持严格（不改 `getattr` 兜底），在 helper 里显式补 `service.bsd_enabled = False` 并写注释 → 19 passed。
`sunnypilot/carrot/tests` 全量：**840 passed / 2 failed（均为上面那条 navi 环境红）**。

## 6. 路试前建议

1. 重启设备，确认 UI 起得来（新增 wheel_controlsd 常驻进程 + 两个设置页条目）。
2. `wheel_controls.json` 为空 → 该守护进程空转，不影响现有按键。
3. 若要带上 xiaoge/speed_limit 那两批，需要单独一轮手工并（各自 2~7 文件冲突面），别混进本轮已绿的这批。
