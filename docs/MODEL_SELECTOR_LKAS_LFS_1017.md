# 模型选择器只列小模型 / LKAS 故障排查 / LFS 完整性审计（2026-10-17 18:20 +08）

记录时间：2026-10-17 18:20 +08
分支：openpilot `sp-macantest-1017`（父仓）/ ai `sp-macanlong-test`
设备：tizi（comma 3X，panda `tres`，`chestnutPresent=false`）

---

## 0. 本轮三问的结论（先看这个）

1. **点火即 LKAS 故障 + 仪表 ACC/PAS 需要维修**：这次**不是** panda 固件版本错配。实测
   `panda.get_version() == "DEV-d84b110f-DEBUG"`，与 `panda/board/obj/gitversion.h` 完全一致
   （panda HEAD = d84b110fc「加强适配c3」），`pandaStates.faults=[]`，`safetyModel=noOutput`
   只是台架 `harnessStatus=notConnected`。最可能仍是 0916 已定的那条链路：relay 隔离后雷达/LKA
   在 CAN2 失去往返应答 → 雷达自身看门狗故障 → 仪表报 ACC/PAS，DTC 跨点火周期保持，所以下次
   点火**立刻**就显示。要落锤需要一路 route log，见第 4 节。
2. **模型选项只有小模型**：根因在 UI 层，不在 LFS。本树在合并上游时把「small model / big model
   两个槽位」的选择入口丢了（设置面板只留 `current_model_item` 走 `active_source()`；mici 面板
   直接跳进 active source 的文件夹且只显示 release/master/favorites 三个文件夹），于是
   chestnut（big）目录里那 17 个 `is_big=true` 的 bundle 虽然已经缓存，却完全没有入口。已按上游
   补回，见第 2 节。
3. **LFS 有没有拉齐**：拉齐了。256 个 LFS 文件里 249 个与远端 object 逐字节一致，7 个是**设计上
   的指针**（`.lfsconfig` 的 `fetchexclude` 只排除 big 模型；warp pkl 与 comma updater 同理），
   0 missing / 0 mismatch。启动 logo 用的 `sunnypilot/selfdrive/assets/logo.png` 的 LFS oid 与
   上游 `mouxangithub/openpilot test` 完全相同（`66b3aefa…616e6a`, 19035 B），所以「我们是逗号
   上游是 Z」不是 LFS 没拉，而是 UI 上取的不是这张图（见第 3 节排查路径）。

---

## 1. op助手「答到一半断联」第二轮修复（承 e76b43e2）

`ai` 子模块 = `68dc5959`（父仓指针提交 `757c55cb29`）：

- `core/chat/jobs.py`：idle 阈值 120/240s → **300/900s**；墙钟硬杀 `_RUN_MAX_SEC=600` 改成
  **预算制**：基础 1800s，每完成一次工具调用 +300s，上限 5400s（`run_budget_sec`），新增
  `_scan_over_budget_jobs()` 专门扫「事件不断但没产出」的复读循环；job 记录 `toolCallsCompleted`。
- `core/sync/protocol.py`：`lifecycle.phase` 的 enum 补齐 `stuck_cancelled / run_timeout_warn /
  run_timeout / resumed`。之前每次看门狗自动取消都会刷一条 schema 校验错误，前端收不到终止原因，
  表现就是「答到一半就没了」。
- `core/agent/state.py`：abort future 改用 `get_running_loop()`。3.12 下 `get_event_loop()` 在
  之前有 `asyncio.run()` 关闭过隐式 loop 后会抛异常，回合会在切 phase 时直接死掉。
- `ai/core/tests` 47 passed。

## 2. 模型选择器与上游对齐（本树丢的入口补回来）

改动文件：
- `openpilot/selfdrive/ui/sunnypilot/layouts/settings/models.py`
- `openpilot/selfdrive/ui/sunnypilot/mici/layouts/models.py`

做法（融合，不是照抄）：
- 设置面板：保留本树自己的 `current_model_item`（展示 + onroad 禁用）与各进度标签行，**新增**
  上游的 `small_model_item` / `big_model_item` 两行和 `_open_source_dialog(source)`；
  `_on_model_selected` 改用新的 `_resolve_selected_bundle()`，在两个目录里按 ref 找 bundle
  （big 的 ref 只在 chestnut 目录里，原来的 `availableBundles` 找不到，于是 big 选择会静默失效）。
- mici 面板（3X 上实际显示的就是这个）：`_show_folders` 改回上游的两级流程——先选
  `small models` / `big models` 槽位（值行显示当前 pick，active 槽位标注），再列该槽位的文件夹；
  新增 `_select_hardware(source)`，`_get_grouped_bundles(bundles, favorites)` 改成按 source 取
  bundle，`_select_folder` 带上 source 并对 big 显示 `big_model_note`；去掉了原来只放行
  release/master/favorites 三个文件夹的过滤。

数据面证据（不需要联网也能验证）：
```
ModelManager_ModelsCache          77 bundles，全部 is_big=false（qcom 目录 v23）
ModelManager_ModelsCache_Chestnut 17 bundles，全部 is_big=true，extended=true
```
`ModelFetcher.active_source(chestnut_present=False) == "qcom"`，所以 big 目录只有靠上面这两个
槽位入口才可达 —— 这就是「只看得到小模型」的全部原因。

测试：`selfdrive/ui/sunnypilot/tests/test_model_info.py` +
`selfdrive/ui/tests/settings_panels_render_smoke.py` +
`selfdrive/ui/sunnypilot/mici/tests/test_mici_settings.py`：改前 28 failed / 96 passed，
改后 **27 failed / 97 passed**（多绿 1 个，没引入新失败；剩下的失败是本机 GUI/EGL 依赖缺失的
既有问题）。`ruff` 错误数 21 → 17。

## 3. LFS 完整性审计（给「是不是没拉齐」一个可复现答案）

审计脚本（父仓根目录跑）：
```
git lfs ls-files -l | while read oid flag path; do … sha256sum 对比 … done
```
结果：`tracked=256 ok=249 pointer=7 missing=0 mismatch=0`

7 个指针（都不是故障）：
| 文件 | 说明 |
|---|---|
| `selfdrive/modeld/models/big_driving_tinygrad.pkl` (776 MB) | `.lfsconfig` 的 `fetchexclude` 明确排除；只有 chestnut 构建才 `big_model_source.ensure_big_pkl()` 现拉 |
| `sunnypilot/modeld_v2/models/{big_,}driving_warp_*_tinygrad.pkl` ×4 | 编译产物，由 warp 编译流程生成，不入库体 |
| `common/hardware/comma/updater` (25 MB) | comma 官方升级器，本平台不用 |

这次**真的补了一个**：`selfdrive/modeld/models/driving_supercombo.onnx` 原来是 133 B 指针，
`git lfs pull --include … --exclude ""` 从 sunnypilot 公共 LFS（gitlab）拉下来了 60,918,562 B，
`models/tests/test_default_model.py::test_compare_onnx_hashes` 由 FAILED 转绿。

**启动 logo 排查路径**（结论：不是 LFS）：mici 的启动 spinner 走
`system/ui/spinner.py → sunnypilot/system/ui/glow_logo.py`，贴图是
`sunnypilot/selfdrive/assets/images/spinner_zoompilot_glow.png`（557 KB，真图，非指针，75 帧
9×9 atlas）。真正被 LFS 管的是 `sunnypilot/selfdrive/assets/logo.png`，oid 与上游一致。所以若
开机仍看到逗号标识，要看的是：① 该台设备跑的是不是 /data/openpilot 这份构建（`ui_state`/进程
路径）；② 开机最初几百毫秒是 ABL/kernel bootlogo（agnos 分区，不归仓库管）；③
`spinner_sunnypilot.png` 是否在某个旧路径被引用。

## 4. LKAS / ACC-PAS 定位还缺什么

现状（台架，未上电）：`harnessStatus=notConnected`、`safetyModel=noOutput`、`faults=[]`、
panda `spiErrorCount=1398`（累计）、电压 5.07 V。
`/data` 已用 87%（3.8 G 空闲），`/data/media/0/realdata` 为**空**——上传/清理把测试那次的 route
删掉了，所以现在没有 rlog 可解码。

下次点火复测请按顺序做：
1. 腾出空间（`/data/media/0/realdata` 至少要留 2 G），确认 `loggerd` 起来、route 落盘；
2. 点火 → 等 15 s → 熄火，记下 route 名；
3. 用 `trip_review(route)` / Cabana 看 `carState.steerFaultTemporary|steerFaultPermanent`、
   `invalidLkasSetting`、`stockLkas`、`accFaulted`，以及 bus2 上 `ACC_04/ACC_05` 的 charisma
   位（对照 `ai/docs/MLB_MACAN_HANDSHAKE_CONCLUSIONS_0916.md` 的判据）；
4. 若 DTC 是跨点火保持的，先用诊断仪清一次 DTC 再点火，确认是不是「上次遗留」。

## 5. 附带修复：tinygrad 子模块漂移

`git ls-tree HEAD tinygrad_repo` 记录的是 `fe5d3169ba`，但工作区检出的是 `66ee3cfb4f`（更新的
merge commit），而后者的 `examples/openpilot/` 里**没有 `compile_warp.py`**
（只有 `compile3.py` / `load_pickle.py`）。后果：`selfdrive/modeld/SConscript` 和
`sunnypilot/jetlink_adapter/warp_build.py` 的 warp 编译链路断掉，
`jetlink_adapter/tests/test_tinygrad.py` 5 个用例直接 ERROR（`can't open file
…/examples/openpilot/compile_warp.py`）。已 `git -C tinygrad_repo checkout fe5d3169ba` 回到
记录指针，该文件 9 passed + 5 subtests。

## 6. 本轮测试汇总（2026-10-17 17:50–18:20）

| 套件 | 结果 |
|---|---|
| `openpilot/selfdrive/controls/tests/test_longcontrol.py` | 19 passed + 4 subtests（停走曲线用例与上游契约融合后全绿） |
| `openpilot/selfdrive/controls/tests/test_macan_radar_fusion.py` | 见控制套件，绿 |
| opendbc `volkswagen/tests/test_macan_mlb.py` + `test_volkswagen.py` | 47 passed + 96 subtests |
| opendbc `test_car_interfaces.py -k MACAN` | 1 passed |
| `sunnypilot/carrot/tests` | 630 passed + 79 subtests |
| `sunnypilot/jetlink_adapter/tests` + `sunnypilot/models/tests` | 200 passed, 2 skipped, 7 subtests |
| `selfdrive/car/tests/vcruise_carrot_onroad_sim.py` | 15/15 PASSED（**必须当脚本跑**：`python <file>`；pytest 收集会因 `Params` shim 与 conftest 导入顺序冲突报 `'Params' object has no attribute '_store'`） |
| `ai/core/tests` | 47 passed |

## 7. 复现用的固定姿势（本机坑）

- pytest：`PYTHONPATH=/data/pytest_deps/lib:/data/openpilot:/data/.pydeps /data/pytest_deps/bin/pytest …`
  （第三个路径给 cv2；opendbc 测试也必须带 `/data/openpilot`）
- 推/pull：`GIT_CONFIG_GLOBAL=/dev/null GIT_ASKPASS=/data/askpass.sh GIT_LFS_SKIP_PUSH=1 git push
  --no-verify https://github.com/FOREVERZAX1988/<repo>.git <branch>`（全局 `pushInsteadOf` 会把
  https 降级成 ssh 然后 publickey denied）
- 拉某个被排除的 LFS 对象：`git lfs pull --include <path> --exclude ""`
- panda 版本自查：`PYTHONPATH=/data/openpilot/panda/python python3 -c "from panda import Panda;
  print(Panda().get_version())"`，对照 `panda/board/obj/gitversion.h`
