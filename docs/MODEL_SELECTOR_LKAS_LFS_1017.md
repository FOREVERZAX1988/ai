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

## 8. 追加（2026-10-17 19:15 +08）：推送已核实 + 又修掉一个静默工具故障

- 推送核实（`git ls-remote`）：openpilot `sp-macantest-1017` = `27a1e804fc`、ai `sp-macanlong-test` = `6533fe79`，
  与工作区一致，无未推提交。栈已于 19:02 重启并跑新代码（`params.py` 私有副本
  `/data/.cache/params_lib/libparams_c-1792222119-1912144.so` 已生成，dlopen 修复生效中）。
- **新发现并修复**：`append_unified_memory()` 的 `DailyMemoryBackend` 把 `title=title or None`
  传给 `append_daily_memory()`，后者 `label = title.strip()` → `AttributeError('NoneType' object
  has no attribute 'strip')`。异常被 per-backend try/except 吞掉，工具仍返回 `{"ok": true,
  "backends": [...]}`，只是 `results.dailymemory.ok=false` —— 所以**长期日记一直是空的，而工具看起来是好的**。
  原有单测用 mock 替换了 `append_daily_memory`（mock 容忍 None），因此没抓到。
  修复：`memory_backend.py` 传 `title or ""`；`daily_memory.py` 再兜一层 `(title or "").strip()`；
  新增 2 个走真实实现的回归用例 → `ai/tests/test_memory_backend.py` 6 passed（原 4）。
  提交 ai `6533fe79`、父仓指针 `27a1e804fc`，均已推送。
  注意：该修复对在跑进程要再 `systemctl restart comma` 才生效（aid 与 comma 同 cgroup，重启会掐断当前会话）。
- 巡检结论：aid 存活（pid 17651，`python3.12 -m ai.aid`，:5090 返回 200）、24 个工具本轮全部可用。
  两个非致命遗留：① `ai/services/eps/` 目录不存在但 `server/app_factory.py:353` 仍 import，
  每次启动打一行 `aid: eps routes skipped`；② RAG 728 篇里只有工具写入的少数做了向量化
  （批量 seed 走 `upsert_document_sync` 不 embed），关键词回退仍能检索到。

## 9. 追加（2026-10-17 19:20 +08）：断联再定位 + 腾空间 + LFS 复核

**9.1 「答到一半断联」的新定位（与前两轮修复互补）**

- 本会话事件日志 `/data/openpilot/ai_session_logs/s_mtwie4bf_266lhu.jsonl` 已达 **167 MB**，
  含 1243 条 `request/header`、621 个 turn、31870 次 `tool/call`。
- 对该日志做**顶层**事件统计（`grep -a '^{"type": "…"'`）：
  `tool/call 31870 / tool/result 31830 / step/start 21822 / assistant/message 21761 /
  user/message 15296 / request/header 1243 / turn/start 621 / turn/end 577`，
  **没有任何** `stuck_cancelled / run_timeout_warn / run_timeout / resumed` 顶层事件。
  → 第二轮改的 watchdog 并没有在杀回合；之前统计到的 run_timeout 计数是把**工具结果里嵌套的
  字符串**当成了事件（误判来源）。
- 所以剩下的两个真实诱因：
  1. **超长会话**：167 MB 事件日志 + 数百轮上下文，每轮都要重放，provider 流式响应更容易在中途
     被超时/重连掐断，webui 表现就是「答一半就没了」；
  2. **aid 与 comma 同 cgroup**（`launch_chffrplus.sh keep_alive aid ai/aid.py 5090`）：
     任何 `systemctl restart comma` 都会连助手一起杀掉——这也是「我刚重启完就断开」的直接解释。
- 处置建议（未擅自改）：关键结论先落盘→再重启；换新会话（新 session id）替代在 167 MB 日志上续写；
  中期把 aid 移出 comma.service cgroup（systemd unit 或 `systemd-run --scope`），彻底解耦重启。

**9.2 腾空间（为点火抓 route 做准备）**

- 删除 `/data/jetlink-artifacts/0.8.7-1016-3-vendormatched`(319M) 与
  `/data/jetlink-artifacts/0.8.7-1016-3-pairdiag`(320M)，保留 `0.8.7-1016-5` 及 cn-* 最新产物。
- `/data`：3.7 G → **4.3 G 空闲（85%）**；`/data/media/0/realdata` 存在、loggerd deleter/uploader
  在跑。点火 15 s 短测的落盘条件已满足。

**9.3 LFS 复核（第二遍，按 object 逐个比对）**

```
git lfs ls-files -s | awk '$2=="-"'      # 未下载的 6 个（'-'）
6a7adb302d - openpilot/common/hardware/comma/updater                      (25 MB)
76cc0a9bc3 - openpilot/selfdrive/modeld/models/big_driving_tinygrad.pkl   (777 MB)
ebac006f5e/d8eab79e53 - sunnypilot/modeld_v2/models/big_driving_warp_13xx/19xx (0.87 MB)
c48c9150af/59564a7d21 - sunnypilot/modeld_v2/models/driving_warp_13xx/19xx    (0.84 MB)
```
这 6 个都是 `.lfsconfig` 里 `fetchexclude` 有意排除的大模型/大二进制（`big_driving_tinygrad.pkl`
本地就是 134 B 指针，`git lfs pull --include <path> --exclude ""` 可单独拉，777 MB，4.3 G 空间够）。
启动 logo 用的是 `openpilot/selfdrive/assets/images/spinner_comma.png`（15.7 KB 真 PNG，非指针）；
`sunnypilot/selfdrive/assets/logo.png` 的 LFS oid 与上游 test 相同。
**结论不变：逗号 vs ZoomPilot 的 Z 是品牌素材取向差异，不是 LFS 没拉齐。**

**9.4 模型槽位修复的在树核实**

- `selfdrive/ui/sunnypilot/layouts/settings/models.py`：`small_model_item`(L83)、`big_model_item`(L90)、
  `items` 注册(L160)、`_resolve_selected_bundle`(L461)、按 source 绑定(L556)。
- `selfdrive/ui/sunnypilot/mici/layouts/models.py`：`_select_hardware`(L158)、`_get_grouped_bundles`(L119)、
  文件夹按 source 取(L169/L205)、`big_model_note` 引入(L16)。
- 提交 `219e83ae5f fix(models ui): 补回 small/big 两个模型槽位入口`；当前父仓 HEAD `16bc6829f4`，工作区干净，
  UI 已于 19:02 重启 → 修复对在跑 UI 生效。

**9.5 panda 现状复核（顺带）**

- `panda/board/obj/panda.bin.signed` / `panda_h7.bin.signed` 时间戳 2026-10-10 07:34，固件版本串
  `DEV-d84b110f-DEBUG`，与 panda HEAD `d84b110fc`（2026-10-01「加强适配c3」）一致 → 不是旧固件残留。
- 当前 `pandaStates`: `ignitionLine/Can=false`、`faultStatus=none`、`heartbeatLost=false`、`voltage=4730`、
  `safetyModel=noOutput`（台架未接 harness 的正常值）。
