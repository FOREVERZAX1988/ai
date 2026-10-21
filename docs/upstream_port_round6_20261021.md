# 上游 test 第 6 轮 — Safe Mode 的元数据与强制层（2026-10-21）

范围：`5ee2c9f618`（`safety: add Safe Mode and the parameter metadata it needs`）的余下部分。
第 5 轮只落了 Python 层（`2960c6b25e`，两条 rules 文件 + 7 个键），本轮补 C++ 元数据与
主循环接入。**默认关，Macan 手感不变**：`SafeMode=0` 时 `enforce_safe_mode()` 第一行就返回 False。

## 搬了什么

| 上游 | 本仓 | 内容 |
|---|---|---|
| `5ee2c9f618` | 本轮 | `params.h` 的 `ParamSettingsTier` + `stock_value`/`tuning_level`/`settings_tier` 三个字段与取值器；`params.cc` 的三个实现（stock 回落 default）；`params_c.cc` 的 `params_get_stock`/`params_get_tuning_level`/`params_get_settings_tier`；`params.py` 的三个绑定 + 同名方法；`control*py` 主循环那 7 行（`frame` 计数 + `enforce_safe_mode(self.params, frame)`） |

`enforce_safe_mode()` 每 `SAFE_MODE_ENFORCE_FRAMES=20` 帧（100 Hz 下 0.2 s）重写一次受管键，
因为设置页和其它 daemon 会写同一批键。实测**幂等**：第二次起返回 False、不写盘（见下）。

## 库重建

`params_keys.h` 的 7 个键第 5 轮就已入表，但 `libparams_c.so` 是编译期产物，本轮新增的三个
C 符号也必须重建才可见：

```
scons -j1 openpilot/common/libparams_c.so     # 44.8 s，一次过，未触发 lowmemorykiller
```

`params.cc` 仍由 `common/SConscript` 钉 `-O0`（`26bfd6962e`），offroad 时 `MemAvailable≈1.49 GB`。
重建后实测（新进程，非 mock）：

```
lib: /data/.cache/params_lib/libparams_c-<mtime>-<size>.so   # 私有副本按 mtime 自动换代
nkeys 730
SafeMode         known stock=b'0'   default=False
SteerRatio       known stock=b'0.0' default=0.0
tuning_level / settings_tier 全部可读（0 / 1）
```

运行中的进程仍映射旧 `.so`，新绑定要重启 manager 才生效；因为 `SafeMode` 默认 0，不急重启。

## 抓到的真 bug：Safe Mode 的写路径在本树全是静默 no-op

上游单测用的是 `Params` 替身，替身收字符串；真 `Params.put` 是**严格类型**的。四处不匹配，
每一处都被 `try/except` 吞掉，所以「测试全绿 + 线上什么都不发生」：

1. `safe_mode.py` 的规则以字符串表述（`"0"` / `"1"` / `"0.0"`），直接写进 BOOL/INT/FLOAT 键时
   `python2cpp` 抛 `TypeError`（`(str, BOOL)` 不在映射里）→ `_put` 返回 False，**一个键都没被强制**。
   修法：在 `_put` 前的 `_coerce()` 里按 `get_type(key)` 转成本类型（含 JSON 转 dict、TIME 转
   datetime、BYTES 转 bytes），转不动就当作「不写」。
2. `_default()` 用 `get(key, return_default=True)`，而该参数只在键**未设置**时给默认值；键一旦设过
   就直接返回**存储值**——于是 `safe_value()` 的「回落注册默认值」分支拿到的正是它要替换的那个值，
   重置变空转。修法：改用 `get_default_value(key)`（键自身的属性）。
3. `_get()` 把 JSON 备份 `str(dict)` 成 Python repr（单引号），`json.loads` 失败 → 解析成「无备份」
   → **restore 永远无效**。修法：`_get` 对 dict/list 原样返回。
4. `_get()` 把 BOOL 读成 `"True"/"False"`，而目标是 `"1"/"0"`，永远不相等 → 每个强制周期把 15 个
   BOOL 键全部重写一遍（5 次/秒）。修法：bool 渲染成 `"1"/"0"`。

修好后真机路径（隔离 Params 目录实测）：`1.53/1/True` → apply → `0.0/0/False`，备份 23 条 →
再次 apply 返回 False（幂等）→ restore → `1.53/1/True`，备份清空。

## 一处刻意的分歧：绑定不硬绑

上游在 import `common/params.py` 时用 `getattr(lib, name)` 硬绑这三个符号。库比代码旧（正是本机
前两周的状态）时那是 **`ImportError` → 所有 import Params 的 daemon 一起起不来**，与这套代码
自己写的「库不认识就当作没有这个参数」完全相反。本树改成 `_bind_optional()`：缺符号只 warning，
`get_stock_value()` 返回 None、`get_tuning_level()` 返回 0、`get_settings_tier()` 返回 1。
「库过期」这件事交给 `test_params_metadata.py` 对真库断言 + 一条显式的降级用例来抓，而不是用
整机起不来的方式抓。

## 新增两道防线（这次事故的形状：替身全绿、真库全哑）

| 文件 | 作用 |
|---|---|
| `common/tests/test_params_metadata.py` | 对**真库**断言三个 C 绑定存在（库比元数据旧就红，附重建 recipe 路径）、受管键已注册、stock 回落、tier/level 可读；并把「我们还没移植的功能键」（`NNFFMode`、`VisionSpeedLimit*`）写成显式豁免集，**双向断言**：键缺失=豁免成立，键出现=功能已移植必须把它从豁免集删掉 |
| `sunnypilot/common/tests/test_safe_mode_store.py` | 对**真库 + 隔离 Params 目录**跑 apply / 幂等 / restore / 行驶中拒 restore / 开关关闭时 no-op 五条端到端 |

## 已知问题，不粉饰

`SAFE_MODE_MANAGED_KEYS` 里 `NNFFMode`、`VisionSpeedLimitEnabled`、`VisionSpeedLimitLowLimitFilter`
三个键本树**未注册**（NNFF = `63a6f3211b`、视觉限速 = `d81eec5899`，都还是 `eval`）。列表保持与上游
逐字一致以便以后拉取，运行时对未知键是 safe 的（读抛异常→跳过，写失败→跳过）。这三条由上面那个
豁免集双向断言盯着，移植完必须回来删。

## 验证

- `sunnypilot/common/tests` + `common/tests`：**183 passed / 258 subtests passed**
- 新增两文件：`10 passed`（真库真 store）
- `ruff`：改动的 4 个 py 文件全绿
- 库重建后真库断言：730 键、`params_get_stock` 等三绑定在位、tuning/tier 可读
- 主循环接线：`control*py` 可 import，`enforce_safe_mode` 在位；`SafeMode=0` 时返回 False

## 下一步

- `dbe9c7c52c`（SLC 限速突降的舒适松弛 + safe-mode stock 语义）— 现在才有 stock 语义可用
- Safe Mode 的 **UI 面**：目前只有参数键、没有开关（与 11 个 `Carrot*Enabled` 那次同形）。
  建议在 Developer 页加一项：开=立即强制，关=调 `restore_safe_mode()`（行驶中会被拒，只能 offroad 关）
- items 其余：`7fd88d270b`+`aab6ed90f8`（watchdog）、`4630b96a77`、`93b695da88`、`0ba6c81d04`
