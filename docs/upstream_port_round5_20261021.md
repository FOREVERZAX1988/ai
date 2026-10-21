# 上游 test 第 5 轮 — modes 状态机 + 安全守卫（2026-10-21）

范围：`upstream/test` 的 items 里两条「独立可搬」的待办，外加它们的 import 前置。
全部默认关，Macan 手感不变。

## 搬了什么

| 上游 | 本仓 | 内容 |
|---|---|---|
| `5ee2c9f618`（部分） | `2960c6b25e` | Safe Mode 的纯 Python 层：`safe_mode.py` / `safe_mode_runtime.py` / 单测，加 7 个参数键 |
| `25112d67f8` | `a9b4ce0b28` | 纵向模式状态机：`mode_state.py`（纯规则）+ `mode_state_runtime.py`（Params 层、flock、写后读回校验）+ carrot server 的 ExperimentalMode 写入口 |
| `a30b14cdab` | `e9ed33666d` | 四道守卫：行驶中禁写行驶相关参数、commIssue 宽限期、过度执行告警可恢复、LFS 指针拒收 |

## 为什么 Safe Mode 必须先落

`mode_state_runtime.py` 第一行就 `from ...safe_mode_runtime import is_safe_mode`。
不先落它，`25112d67f8` 不是「没搬完」，是 import 就断。

只搬了 Python 层，C++ 元数据（`stock_value` / `tuning_level` / `settings_tier` +
`get_stock_value` 绑定）和主循环那 7 行强制回保守值**没搬**，留在 items 里，
status 降为 `partial`，探针改成查 `params.h` 里 `get_stock_value` 是否仍缺席。
在强制层落地前 `SafeMode` 键是惰性的；Python 层每次读元数据都自带 try/except，
缺绑定只会「不动这个参数」，不会抛。

## 库重建

`params_keys.h` 加 7 键后按既有 recipe 单目标重建：

```
scons -j1 openpilot/common/libparams_c.so
```

`params.cc` 由 `common/SConscript`（`26bfd6962e`）钉在 `-O0`。
本次实测峰值 **265 MB / 38.9 s**，没触发 lowmemorykiller——与整机 `-O2 -g` 那次
（1.9 GB 被 SIGKILL）是两种完全不同的形状。
代价：运行中的进程仍映射旧 `.so`，新键在重启后才可见；因为默认 0，不急重启。

## 抓到的真 bug：测试在写真机的参数

`test_carrot_server_params.py` 的类注释写着「real (isolated) Params store」，
实现只是 `from openpilot.common.test import OpenpilotPrefix  # noqa: F401`——
**import 不会隔离**。C++ 侧在构造 Params 时读 `OPENPILOT_PREFIX`，
没进 prefix 就是真 `/data/params`。

后果：这批测试在开发过程中把车的 `ExperimentalMode` 和
`ExperimentalModeConfirmed` 都写成了 1。定位靠
`/data/carrot/state/param_changes.jsonl`——里面 `prev: False` 直接给出了原值，
已按原值写回 0（当时 offroad、点火关）。

修法：`asyncSetUp` 在 `create_app()` 之前真正 `OpenpilotPrefix().__enter__()`，
`asyncTearDown` 退出。验证方式是比 mtime——整轮跑完 `/data/params/d` 不再变。

## 已知问题，不粉饰

`test_param_set_then_params_bulk_round_trip` 间歇红：跨文件跑约 15 次红 2 次，
单文件跑约 10 次全绿，之后连跑 5 次未复现。怀疑跨模块
`sys.modules["openpilot.common.params"]` 桩污染（同一文件 `_FakeParams` 的注释
已记录同类问题）。记进 registry 的 `known_issues`，没有假装绿。

## 验证

- `test_mode_state.py` + `test_safe_mode.py`：55 passed
- `test_carrot_server_params.py`：29 passed / 29 subtests（连跑 3 次）
- `sunnypilot/common/tests` + `sunnypilot/models/tests`：256 passed / 2 skipped
- `test_safety_guards.py` + `test_chunked_download.py`：28 passed
- 守卫实测：行驶中写横向参数被拒（400 + 原因），写 `IsMetric` 放行
- ruff：1 条既有 `F841`（`selfdrived.py:212` 的 `is_remote`），本轮未新增
- registry checker：phase 2 `10/10 still unported as recorded`、phase 3 `4/4 consistent`，无 DRIFT

## 下一步

- `5ee2c9f618` 余下：C++ 元数据 + 主循环强制层（改 `params.cc`/`params_c.cc`，需重编库）
- `dbe9c7c52c`（SLC 限速突降的舒适松弛）— 依赖 Safe Mode 的 stock 语义
- items 其余：`7fd88d270b`+`aab6ed90f8`（watchdog，C++ 新目标）、`4630b96a77`（模型体积台账）、
  `93b695da88`（雷达点叠加档位，本树无 ShowRadarInfo）、`0ba6c81d04`（大 UI 的 Rear Camera 一节）
- 评估项：`d81eec5899`（视觉限速，2883 行 + 22MB）、`63a6f3211b`（NNFF，127 文件）
