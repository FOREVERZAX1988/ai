# 上游未移植清单：逐条可判定表（2026-10-23）

> 生成方式：`ai/scripts/upstream_divergence_check.py --pending-only` ＋ registry 逐条探针；
> 判据不是「hash 差集」，而是**本树里路径/符号的存在性**（或子模块祖先关系）。
> 一条 item 的探针全部成立才算「仍未移植」；任一探针失效，checker 报 DRIFT，说明我们其实已经搬了或上游又改了。

## 0. 上游是否有新东西没拉

| 检查 | 结果 |
|---|---|
| `git fetch upstream 'refs/heads/*:refs/remotes/upstream/*'` | rc=0，无新对象 |
| `upstream/test` tip | `684178cb51 2026-10-23 feat(carrot): section average-speed control on the SDI chain` |
| `git ls-remote upstream refs/heads/test` 交叉核对 | `684178cb5120224613db43355841f5207e9d59a4`（一致） |
| registry `scope.upstream_tip` | `684178cb51`（一致） |

**结论：上游没有我们没拉取的更新。** 25 条不是「25 条待搬」，分解见下。

## 1. 25 条的账目（25 = 6 + 6 + 13）

| 类别 | 条数 | 含义 |
|---|---|---|
| 已用等价提交落地 | 6 | 上游 hash 与我们 hash 不同，内容已进本树 |
| 未移植·本轮前就有探针 | 6 | `items` 里原有，机器可判定 |
| 未移植·原先「无探针」 | 13 | 本轮全部补成 path/symbol 探针，`unported_unprobed` 清空 |

另外 registry 里还有 2 条**不在** 25 条差集内，原因写在表后的注 1/注 2。

## 2. 逐条表

| # | 上游提交 | 主题 | 判定 | 判据（本树实测） | 依赖 / 动作 |
|---|---|---|---|---|---|
| 1 | `684178cb51` | feat(carrot): section average-speed control on the SDI c | 已落地 | 等价本地提交 `c0b3171e66`；test_section_average + test_speed_limit_resolver 55 passed；test_carrot | 无 |
| 2 | `e3cf1856c9` | 更新 | 不搬（已判定） | `submodule_not_ancestor` opendbc_repo :: 52ab072204b58be9ad8f540a5b2bb5003a2f3a -> OK (pin 52ab072204 not in opendbc_repo@61f4cc848) | 内容为空壳（只有文档+指针）；指针判定随 ee23033248 走 |
| 3 | `4ff945e764` | test(carrot): replace module eviction with a config.Para | 未移植·有前置 | `path_absent` openpilot/sunnypilot/carrot/server/tests/test_system_monitor.py -> OK (absent: openpilot/sunnypilot/carrot/server/tests/test_system_monitor.py) | test_system_monitor.py 由 8e51f886d9 新建；test_carrot_man.py 本树已存在，可独立先改 |
| 4 | `4c4c654fef` | test(server): add missing tests/__init__.py so unittest  | 已落地 | 等价本地提交 `5567678adb`； | 无 |
| 5 | `8a7e93181d` | test(carrot): fix cross-module Params pollution and a fl | 已落地 | 等价本地提交 `ba96418ec9`； | 无 |
| 6 | `b82043d2a7` | test: align two stale pins with today's appends | 已落地 | 等价本地提交 `4c4e086183`； | 无 |
| 7 | `b5061ca8c4` | launch: fix ensure_params_build parallelism — nproc retu | 已落地 | 等价本地提交 `0d6fc24ea4`； | 无 |
| 8 | `1e97bf13a9` | test(capnp): pin blindspot split fields at @75-79 after  | 未移植·有前置 | `path_absent` openpilot/sunnypilot/carrot/tests/test_capnp_contract_guard.py -> OK (absent: openpilot/sunnypilot/carrot/tests/test_capnp_contract_guard.py) | 该用例文件本身由 2fe4acf5dc 新建；它钉的字段由 opendbc 52ab0722 引入，本树 opendbc pin 里 car.capnp 还没有 split 字段，三条一起动 |
| 9 | `1c162bcae3` | fix(mpc): jerk_channels import path - module lives under | 未移植·有前置 | `symbol_absent` openpilot/selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py :: jerk_channels -> OK (no jerk_channels) | 搬 29174dca73 时直接采用修正后的 sunnypilot 路径，不要先搬错的再修 |
| 10 | `ee23033248` | 更新 | 未移植·子模块指针 | `submodule_not_ancestor` opendbc_repo :: 52ab072204b58be9ad8f540a5b2bb5003a2f3a -> OK (pin 52ab072204 not in opendbc_repo@61f4cc848) | 最终 pin 是 52ab0722（4 条领先本树 61f4cc848）；本树 opendbc 与上游非直系（282 条本地独占），不能快进，要单独评估 |
| 11 | `5af396b880` | test(wheel_controls): make unknown-keycode fallback inde | 未移植·有前置 | `path_absent` openpilot/sunnypilot/system/wheel_controls/tests/test_wheel_controls.py -> OK (absent: openpilot/sunnypilot/system/wheel_controls/tests/test_wheel_controls.py) | 无 |
| 12 | `67ffbe9f03` | xiaoge: adopt cp's three-class BSD classifier with dual- | 未移植·待评估 | `path_absent` openpilot/sunnypilot/carrot/tests/test_xiaoge_bsd_semantics.py -> OK (absent: openpilot/sunnypilot/carrot/tests/test_xiaoge_bsd_semantics.py)<br>`symbol_absent` openpilot/common/params_keys.h :: "OnnxBsdThreshold", {PERSISTENT \| BACK -> OK (no "OnnxBsdThreshold", {PERSISTENT \| BACKUP, INT, "94") | 2fe4acf5dc |
| 13 | `29bfad171c` | fix(build): repair SConstruct syntax - except clause mer | 未移植·有前置 | `symbol_absent` SConstruct :: scons_cache_lock -> OK (no scons_cache_lock) | 本树 SConstruct 现在还没有 cache-lock 段，所以这条是「不为空」的：它只能随 2fe4acf5dc 一起进，且必须取修复后的断行版本 |
| 14 | `ad617598df` | feat(wheel_controls): generic USB/BT input layer - zero  | 未移植·待评估 | `path_absent` openpilot/sunnypilot/system/wheel_controls/wheel_controlsd.py -> OK (absent: openpilot/sunnypilot/system/wheel_controls/wheel_controlsd.py) | 无 |
| 15 | `8e51f886d9` | feat(carrot): /api/system_monitor - read-only process/CP | 未移植·可独立搬 | `path_absent` openpilot/sunnypilot/carrot/server/services/system_monitor.py -> OK (absent: openpilot/sunnypilot/carrot/server/services/system_monitor.py) | 无 |
| 16 | `2e60e286ac` | feat(carrot): executable favorite slots - one-tap toggle | 未移植·可独立搬 | `path_absent` openpilot/sunnypilot/carrot/server/tests/test_favorite_slots.py -> OK (absent: openpilot/sunnypilot/carrot/server/tests/test_favorite_slots.py) | 无 |
| 17 | `9410aec458` | 更新memory | 不搬（已判定） | `path_absent` AGENTS-memory.md -> OK (absent: AGENTS-memory.md) | 我们是 ai/ 体系，不携带该文件；故意不搬 |
| 18 | `f1751249ae` | docs(xiaoge): why the two YOLO detectors coexist and why | 未移植·文档 | `symbol_absent` openpilot/sunnypilot/carrot/xiaoge/xiaoge_vision.py :: Same value as the blind-spot window on -> OK (no Same value as the blind-spot window on purpose) | 7ed16d83a6 |
| 19 | `b660e1416c` | fix(speed_limit_vision): subscribe only to services this | 已落地 | 等价本地提交 `46b709561b`； | 无 |
| 20 | `7ed16d83a6` | feat(xiaoge): YOLO obstacle head — inference, server wir | 未移植·待评估 | `path_absent` openpilot/sunnypilot/carrot/xiaoge/yolo_inference.py -> OK (absent: openpilot/sunnypilot/carrot/xiaoge/yolo_inference.py) | 无 |
| 21 | `2dc4d8de39` | feat(alerts): e2e standstill chimes while cruise engaged | 未移植·可独立搬 | `symbol_absent` openpilot/common/params_keys.h :: E2EAlertsWhenEngaged -> OK (no E2EAlertsWhenEngaged)<br>`path_absent` openpilot/sunnypilot/selfdrive/controls/lib/tests/test_e2e_alerts_helper.py -> OK (absent: openpilot/sunnypilot/selfdrive/controls/lib/tests/test_e2e_alerts_helper.py) | 无 |
| 22 | `fa32bf598b` | fix(vasm,signal): close BSD refresh race, clear stale re | 未移植·有前置 | `symbol_absent` openpilot/sunnypilot/carrot/xiaoge/v_asm_server.py :: settings_refresh_lock -> OK (no settings_refresh_lock)<br>`symbol_absent` openpilot/sunnypilot/carrot/xiaoge/v_asm_server.py :: bsd_generation -> OK (no bsd_generation) | 2fe4acf5dc |
| 23 | `2fe4acf5dc` | feat(carrot): port cp P0-P2 batch — UI diagnostics, coas | 未移植·待评估 | `path_absent` openpilot/common/scons_cache_lock.py -> OK (absent: openpilot/common/scons_cache_lock.py)<br>`path_absent` openpilot/selfdrive/ui/render_diagnostics.py -> OK (absent: openpilot/selfdrive/ui/render_diagnostics.py)<br>`symbol_absent` openpilot/common/params_keys.h :: OnnxBsdEnabled -> OK (no OnnxBsdEnabled) | 搬它必须连带 29bfad171c（SConstruct SyntaxError 修复）否则 boot 期 scons 直接死 |
| 24 | `29174dca73` | feat(speed_limit,mpc,dec): tiered offsets, three-channel | 未移植·待评估 | `path_absent` openpilot/sunnypilot/selfdrive/controls/lib/speed_limit/tiered_offset.py -> OK (absent: openpilot/sunnypilot/selfdrive/controls/lib/speed_limit/tiered_offset.py) | 无 |
| 25 | `564e8e93c8` | merge: pull the test branch onto zoompilot's develop | 不搬（已判定） | （无单点探针，见注） | 不逐条搬；其效果等于 eeb028a58(panda) + ee23033248(opendbc) 两个指针条目，分别由那两条判定 |

### 注 1 — panda 指针 `eeb028a58`（不在 25 条里）

upstream/test 的 `panda` gitlink = `eeb028a58`，本树 = `d84b110fc`；该 bump 是被上游 merge `564e8e93c8` 带进来的，
所以在 `HEAD..upstream/test` 的提交序列里没有单独一条。判定只能靠子模块祖先关系：
`submodule_not_ancestor panda eeb028a58` -> OK（panda@d84b110fc 里不含它）。
既有纪律是 tizi 设备上 panda 保持不动，本轮不碰。

### 注 2 — `2e36dcdd71` 已证伪，移出未移植清单

registry 原把它登记为「未移植的 merge 文档提交」，实测：
- `git merge-base --is-ancestor 2e36dcdd71 HEAD` → **YES**（它已经在我们的历史里）
- `git merge-base --is-ancestor 2e36dcdd71 upstream/test` → **NO**（上游 test 反而不含它）

即它从来不该出现在「未移植」里。已移入 `upstream_pending_port.merged_in` 留档。

## 3. 两条「搬到一半」的上游补丁 —— 必须连体搬

这是本轮最值得记住的：上游自己在同一天先搬了会崩的东西、再补修，我们把「修」当成了独立条目。

| 上游补丁 | 它修的是 | 在本树的状态 |
|---|---|---|
| `29bfad171c` fix(build): SConstruct syntax | `2fe4acf5dc` 把 `except` 并到了 `try` 同一行 → 每次 scons 都 SyntaxError，设备显示 “sunnypilot failed to build” | 本树 `SConstruct` 还没有 cache-lock 段（`grep -c scons_cache_lock SConstruct` = 0），所以这条只能**随 2fe4acf5dc 一起进，且取断行后的版本** |
| `1c162bcae3` fix(mpc): jerk_channels import | `29174dca73` 从 `openpilot.selfdrive...` 导入 `jerk_channels`，而模块在 `sunnypilot/selfdrive/...` → acados 生成期崩，unit 起不来 | 本树 `long_mpc.py` 里 `jerk_channels` 出现 0 次；搬 `29174dca73` 时**直接用 sunnypilot 路径**，别先搬错的再修 |

## 4. 依赖分组（建议的搬运批次）

| 批次 | 条目 | 说明 |
|---|---|---|
| 批次 A（无前置，可先动） | `2dc4d8de39` `2e60e286ac` `8e51f886d9` | 各自独立；8e51f886d9 是 4ff945e764 的前置 |
| 批次 B（大件，需拍板） | `2fe4acf5dc` + `29bfad171c` + `1e97bf13a9` + `67ffbe9f03` | 38 文件 1814 行，跨 UI/控制/cereal；1e97bf13a9 的用例文件本身就由 2fe4acf5dc 新建 |
| 批次 C（xiaoge/vision） | `7ed16d83a6` + `f1751249ae` + `fa32bf598b` | YOLO 头 + 两检测器共存注释 + BSD 刷新竞态 |
| 批次 D（输入层） | `ad617598df` + `5af396b880` | 通用 USB/BT 输入层与其测试 |
| 批次 E（控制参数） | `29174dca73` + `1c162bcae3` | 分级偏移/三通道 jerk/DEC；连体搬 |
| 指针层 | `eeb028a58`(panda) `ee23033248`/`e3cf1856c9`(opendbc) `1e97bf13a9`(capnp pin) | 见 §5 |

## 5. 指针层的三条耦合（本轮的第二个发现）

| 对象 | 本树 | upstream/test | 关系 |
|---|---|---|---|
| `panda` | `d84b110fc` | `eeb028a58` | 上游领先；tizi 上不动 panda 是既有纪律 |
| `opendbc_repo` | `61f4cc848` | `52ab07220` | 上游领先 **4 条**（`8c12b1236` vCluRatio/speedLimitDistance/logCarrot、`a8b81c552` 盲区 split 字段、`52ab07220` 把 split 钉到 @75-79、`a3c88c85e`）；**非直系**——本树 opendbc 有 282 条上游没有的提交，不能快进，只能人工合并 |
| cereal 字段 | `opendbc_repo/opendbc/car/car.capnp` 只有一行注释 `# blindspot sensors` | 含 split 字段 | 所以 `1e97bf13a9`（把 split 钉在 @75-79 的 capnp 守卫测试）与本树现状**对不上**：字段还没进来，测试文件也还不存在 |

## 6. 本轮 registry 改动

1. `unported_unprobed`（13 条）全部补上 path/symbol 探针，提升为 `items` → 现在 **20 条 items 全部机器可判定**。
2. `2e36dcdd71` 移入 `merged_in`（已被证伪为「未移植」）。
3. `entries` 两处登记失真修正（都是**不是本地回归**的那种红）：
   - `test_longitudinal_planner.py`：旧登记的三条 upstream intent（`_carrot_is_a_competing_target()` 守卫、`_StubScc(.vision/.map)`）**在两个树里都不存在**，是从未落地的设想被写成「我们保留的差异」；实测该文件与上游逐字节一致 → 改为 `expect_diff=false` 并按真实断言重写。
   - `test_absolute_imports.py`：上游根本没有这个文件（本地独有，且带一条「上游同源红」）→ 标 `local_only`，checker 新增该分支，不再报 MISSING。

## 7. 复跑证据

```
$ python3 ai/scripts/upstream_divergence_check.py
  [phase 0] remote.upstream.fetch  OK
  [phase 1]    => 32/32 as expected          # 原 30/32（1 FAIL + 1 MISSING）
  [phase 2]    => 20/20 still unported as recorded
  [phase 3]    => 4/4 consistent
EXIT=0
```
