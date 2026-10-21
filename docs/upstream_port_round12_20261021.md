# 上游 test 第 12 轮 — 视觉限速（daemon + 喂进限速解析）（2026-10-21）

范围：`d81eec5899`（reader）→ `d4136d1df0`（feed）。这是登记表最后两条非 NNFF 的 eval，
也是驾驶者明确点名要的那一对。工序按依赖走：A 只把 daemon 与资产落地（开关默认关），
B 才把结果接进 `speed_limit_resolver`，中间不停机、不重启进程。

## 一、A：视觉限速 daemon（`9a263c5945`）

`openpilot/sunnypilot/system/speed_limit_vision.py`（2883 行）+ `common/cpu_throttle.py` +
三个 US 模型（detector 9.6 MB、reject 6.2 MB、value 6.2 MB，合计约 22 MB，走
`.gitattributes` 覆写成普通 blob，不需要 LFS 推权）+ 25 条纯逻辑测试。

- 入口是 **进程管理器门**：`speed_limit_vision_enabled(started, params, CP)` =
  `started and SpeedLimitVisionEnabled and not CP.passive`。默认 0，所以 Macan 上
  「搬完了」与「车行为变了」是两件事。
- 订阅 `deviceState / mapdOut / procLog / livePose / carState`，摄像头走 VisionIpc 的 road 流；
  `cv2` 与 `messaging` 都是懒导入，offroad 起这个模块不加载推理栈。
- 本分叉没有 `visionSpeedLimitBookmark` 这个 cereal 通道，书签路径是上游自己就 stub 掉的，
  搬过来保持 stub。

## 二、B：喂进解析器（`84edbe5b55`）

`vision_limit.py`（纯规则：新鲜度、低限速误读过滤、只取更低值）+ resolver 侧把它折进 `map` 源：
地图限速仍是权威，视觉只能收紧；进门前先和 road/map 参考速度比一遍。三个新键
`VisionSpeedLimitEnabled`（默认 0，唯一必须开的那个）、`VisionSpeedLimitLowLimitFilter`、
`VisionSpeedLimitLowLimitThreshold`。

**这一轮踩到的是同一个老坑，但这次是量出来的**：第一遍直接搬上游的 `params.get_bool`，
`speed_limit/tests` **35 failed / 100 passed**，报错全是
`UnknownKeyName: b'VisionSpeedLimitEnabled'` —— 键写进了 `params_keys.h`，但设备上的
`libparams_c.so` 还是旧的。改成 `param_read.read_bool / read_float` 后 **135 passed**。
所以「权限门控读走 param_read」不是洁癖，是这台机器上不重编库就起不来 plannerd 的直接原因。

## 三、库重建（这次没有 LMK）

- 单目标：`scons -j1 openpilot/common/libparams_c.so`，offroad（`started=false`）
- 耗时 39.9 s，**峰值 RSS 266 MB**（`/usr/bin/time -v`），构建前后 `MemAvailable`
  1424 MB → 1420 MB，进程未被杀
- `strings` 三个新键全部出现；设备侧 `Params().get_bool` 读得到（False/False，threshold 0.0）
- 现钉的是 `common/SConscript` 的 `-O0`（`26bfd6962e`）。`-O1 -g0` 的峰值实测仍是
  `ai_todos` 里的待办，判据不变（VmHWM < 1.2 GB 才升级钉）

## 四、屏幕上够得着（`541d96a3d7`）

Developer 页新一节 **Vision Speed Limit (default off)**：Vision Sign Reader / Feed Vision Limit /
Drop Impossible Vision Limits，每行都写清「要不要重启」。三个键都不是 `Carrot*`，
`audit_ui_reach.py` 的 `NAME_RE` 看不见它们 —— 和上一轮 FLM 那两个键是同一个盲区，所以照同样的
做法进 `EXTRA_CONTROL_PARAMS` + `NOTES`。

`SpeedLimitVisionEnabled` 故意**不进** EXTRA：它是进程管理器门，不在控制路径上，列进去会让
审计表声称一个并不存在的读点（`test_the_extra_family_list_still_matches_live_switches` 会红）。

重生成的表：控制路径开关 **24 个，23 个有 UI 入口，1 个没有** —— 剩下那个是
`VisionSpeedLimitLowLimitThreshold`。**这是已知缺口**：它决定「丢弃阈值」，单位是 m/s，
做成滑轮在屏上要么误导（驾驶员以为是 km/h）要么还得带单位换算，本轮先留在 API，
等驾驶者说要不要按 km/h 显示再补一行。注意它默认 0.0 时 filter 等于空转 ——
只开 filter 不开阈值不会有任何效果，这一点写进标签文案里了。

## 验证

- `test_speed_limit_vision_pure.py`：**25 passed**
- `speed_limit/tests`（含新 `test_vision_limit.py`）：**135 passed**（改 param_read 之前 35 failed）
- `test_carrot_ui_reach.py`：**7 passed**
- `ruff`：新文件 0；`carrot_tuning_items.py` 44→39（与 HEAD 基线同一个 39，0 新增）
- 登记表：`ai/docs/upstream_divergence_registry.json` items **3 → 1**（只剩 NNFF），
  entries 24 条（新增 resolver 那条 mixed：三个门控改 param_read 是本树刻意的分叉）
- `upstream_divergence_check.py --side worktree`：phase 2 **1/1**、phase 3 **4/4**；
  phase 1 是 **23/24**，唯一的 FAIL 是 `cereal/log.capnp`

## 下一步

1. **phase 1 那个 FAIL 不是本轮引入的，但它指向真的新上游**：
   `openpilot/cereal/log.capnp` 比 `upstream/test` 少 3 行 `modeldLaggingMild @106`
   （上游 `927498237f` selfdrived 把 modeldLagging 拆成 mild/severe 两档）。这条要连
   selfdrived 侧一起搬，单搬 capnp 只会多一个没人写的枚举。
2. **上游 test 已经又走了 19 个提交**（`4630b96a77..72c6200b79`）：modes 单一门控、
   Safe Mode 入口、params 调参深度声明（webui 侧四个控件）、modeld 分阶段耗时、
   watchdog 清扫孤儿心跳文件……这是一整轮的量，建议按登记表分 3 批。
3. NNFF（`63a6f3211b`，127 文件）仍是唯一 eval：要驾驶者先拍板「多一个横向神经网络前馈」
   值不值，Macan 没有对应的用户群体。
