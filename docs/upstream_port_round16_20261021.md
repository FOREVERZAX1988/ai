# 上游搬运 第 16 轮（2026-10-21）

基线：本树 `sync/upstream-1019`，起点 `d5d5e1c560`（round 15 收口），终点 **`853cc6f936`**。
round 15 收口时 `upstream/test` 已在 `1b36f1ad36`，本轮启动时 `git fetch upstream test` 仍在
`1b36f1ad36`（`git rev-list --left-right --count HEAD...upstream/test` = 673/107，107 条全是历史分叉，
`git cherry` 报 101 条「缺口」是因为我们的移植是改写式提交、patch-id 不同，不是没搬）。

## 1. 结论先说

`63a6f3211b` NNFF 是**上游最后一条未移植功能**，本轮搬完。登记表 `upstream_pending_port.items`
从 2 条降到 1 条，剩下那条是 `0facf5cf71`（agnos 腾讯镜像，非 comma 硬件，skip）。

## 2. 第 15 轮把它压成 `eval` 的理由是错的

当时的说法是「127 个文件 / 模型资产要单独推（LFS/分块），体积与延迟都需要驾驶者拍板」。实测：

```
121 个 nnff_models/*.json  合计 0.6 MB，最大 19 KB，平均 5 KB
6 个代码文件                621 行（其中测试 144 行）
```

没有 LFS，没有分块，也没有值得让驾驶者等的体积问题。`git ls-tree -r -l` 量的，不是估的。

## 3. 按字节搬过来的部分（与上游逐字节一致）

| 文件 | 行数 |
|---|---|
| `controls/lib/nnff_model.py` | 170 |
| `controls/lib/nnff_variables.py` | 50（改 1 处，见 §4） |
| `controls/lib/latcontrol_nnff.py` | 231 |
| `controls/lib/tests/test_latcontrol_nnff.py` | 144（17 例，**未改一行就全绿**） |
| `selfdrive/assets/nnff_models/*.json` | 121 个 |

搬法统一用 `git checkout 63a6f3211b -- <paths>`，不手抄。

## 4. 三处必须自己适配的地方

**(a) `nnff_supported()` 的 import 是空指针。** 上游写成

```python
from openpilot.selfdrive.controls.lib.neural_network_feedforward import get_nn_model_path
```

`neural_network_feedforward.py` 是**更晚**一次改名才有的模块，本树没有。照搬的话这个函数一调用就
`ImportError`——函数「看起来在」，其实永远给不出答复。改成从 `nnff_model` 取，签名与 `""` 通配语义不变。

**(b) 控制器没有 `extension`，而本树每帧都在摸它。** 这是本轮真正的价值点，详见 §5。

**(c) `update_live_torque_params` 在上游是死代码。** 上游定义了它（`latcontrol_nnff.py:88`），但
`git grep 63a6f3211b` 显示**没有任何调用点**。也就是说上游开着 NNFF 时，控制器永远拿 `CarParams`
里的默认扭矩参数，`lateralTorqueParameters`（学到的 latAccelFactor/friction）一条都进不去。本树把它
接成了 fallback，顺手把这个上游 bug 一起修掉。

## 5. 两处会把车开成「没有横向控制」的坑（上游没有，因为上游没有我们的 extension）

本树（zoned tune / FLM / lane assist / speed-dep）与上游最大的结构差异：**横向控制器的 `extension` 对象**。
`latcontrol_torque.py` 里 `self.extension = LatControlTorqueExt(...)`，然后每帧：

```
controlsd.py      update_torque_parameters / extension.update_limits / update_model_v2 / update_lateral_lag / update_curve_speed
controls_lateral_zp.py  dispatch_speed_bins → 对 self._lacs 里每个控制器的 extension.update_speed_dep_torque
```

`LatControlNNFF` 继承的是 `LatControl`，不是 `LatControlTorque`——**没有 extension，方法名也不同**
（`update_live_torque_params` vs `update_torque_parameters`）。所以照抄上游会得到：

- `NNFFMode > 0` 时，横向一激活的第一帧就 `AttributeError`；
- offroad 冒烟测试**永远看不到**，因为只有开起来才会进 `state_control`；
- 现场表现是「打开一个设置项，横向直接没了」。

处理：两处都改成 `getattr(..., 'extension', None)`；live 参数走
`getattr(self.LaC, 'update_torque_parameters', None) or getattr(self.LaC, 'update_live_torque_params', None)`。
语义写清楚：**NNFF 生效时本树的 overlay 不跑**，这是诚实的——NNFF 是替换那套数学，不是在它上面叠加。

## 6. 这台车用不了，怎么让屏幕自己说

`PORSCHE_MACAN_MK1` 在上游 121 个模型里**一个 PORSCHE 都没有**，`opendbc/car/torque_data/substitute.toml`
里也没有 PORSCHE 行（132 行全查过）。源头验证：

```
get_nn_model('PORSCHE_MACAN_MK1', '')  -> None      # 本车
get_nn_model('TOYOTA_RAV4', '')        -> .../TOYOTA_RAV4.json   # 正控，证明匹配器没坏
```

`get_nn_model()` 返回 None ⇒ `nnff_loaded = False` ⇒ lite/full 两个分支都进不去 ⇒ 任何 `NNFFMode`
取值都跑经典扭矩数学。按驾驶者 2026-10-21 的口径（拉代码 + 本车不支持就灰掉），落成两件事：

1. `feature_support.UNSUPPORTED` 加一行 `NNFFMode`（`off=0`，INT 不是 bool），carrot_server 启动时
   把从别的车备份恢复出来的值强行写回 0；
2. Developer 页加一行 **NNFF Lateral Feedforward** 步进器（0=Off / 1=Lite / 2=Full），本车渲染灰色、
   默认关、点不动，描述里带原因。

## 7. 护栏（都做了反证）

| 用例 | 内容 |
|---|---|
| `test_nnff_integration.py`（7 条，新增） | 本车无模型；控制器不加载模型且 mode=2 仍走 stock；有模型的车确实加载（正控）；AST 契约：不许再出现直接的 `self.LaC.extension` / `lac.extension`，不许丢 live 参数 fallback，不许丢每秒重读 mode |
| `test_feature_support`（16 条） | 页面扫描从 `carrot_tuning_items.py` 扩到 **+ `developer.py`**，所以新行不接 `enabled=` 会红 |
| `test_params_metadata`（6 条） | `UNPORTED_MANAGED_KEYS` 现已清空——`NNFFMode` 注册了，这正是那条断言存在的意义 |

反证做法：把 `getattr` 改回 `self.LaC.extension` → 护栏报 `lines [147] touch the extension directly`；
把 `enabled=` 删掉 → 报 `NNFFMode has a switch on a settings page but no enabled= wiring`；
把 zp 那处改回直取 → 报 `controls_lateral_zp.py: lines [146]`。三处都能真红，然后都改回去了。

## 8. libparams_c.so 重建（新键必须重建，否则「静默不生效」）

`NNFFMode` 加进 `common/params_keys.h`（放在 `CurvatureLearningData` 之后，与上游同一槽位，方便以后
对位）。`keys` 是编译期表，不重建 `.so` 就是全进程读不到。按
`ai/docs/libparams_c_rebuild_recipe_20261021.md` 单目标重建：

```
scons -j1 openpilot/common/libparams_c.so
  [CXX] openpilot/common/params.o
  [LINK] openpilot/common/libparams_c.so
  Elapsed 2:31.90   Maximum resident set size 368940 KB (368.9 MB)
```

**新的实测点**：这次开工前 `MemAvailable` 只有 **1337 MB**（配方文档记的是 1.9 GB 充裕情形），
`-O1 -g0` 的 368.9 MB 峰值仍然活下来了 —— 说明 `ac4bc9fe07` 那个 pin 的余量比文档假设的更小也能用。
建议后续把判据从「offroad MemAvailable > 1.9 GB」放宽到「> 1.2 GB」。

重建后验证（读的是私有副本，不是 checkout 里那份）：

```
keys 总数 731 / NNFFMode 已注册 True / 类型 INT / 默认 0
```

## 9. 验证数字

| 套件 | 结果 |
|---|---|
| `openpilot/selfdrive/controls/lib/tests` | **266 passed**, 1 skipped（round 15 是 259 passed，+7 就是本轮新增） |
| `openpilot/sunnypilot/selfdrive/controls/lib/tests` | **344 passed** |
| `openpilot/sunnypilot/selfdrive/controls/tests` | 68 passed + 1 failed + 1 collection error，**两条都是既有**（`test_bins_taken_as_published` 用 `git stash` 把我的改动摘掉后同样红；`test_lead_data_field_map.py` 缺 `cereal`） |
| `openpilot/common/tests` | **64 passed / 258 subtests** |
| `carrot/tests/test_feature_support.py` | **16 passed** |
| ruff | 触碰的 8 个文件全绿（`developer.py` 剩的 4 条 ISC002 是既有，改动前后都是 4 条） |

## 10. 登记表现状

- `entries` 24 → **26**：新增 `controlsd.py`（verdict=ours，含 4 条 ours_keeps / 3 条 upstream_intent_present）
  与 `nnff_variables.py`（verdict=mixed）。检查器 **26/26 as expected**。
- `upstream_pending_port.items` 2 → **1**（只剩 agnos skip，1/1 still unported）。
- `ported` 81 → **82**。
- phase 3 已推迟钩子 **4/4 consistent**。

## 11. 下一轮

上游代码层面**已经没有未移植项**了。剩下的全部是驾驶者侧动作，登记在 `ai_todos/todos.json`：

1. **屏幕验收新行**：设置 → Developer → `NNFF Lateral Feedforward` 应为灰色、默认 Off、点不动、
   描述带「No torque model for a Macan …」。它同时是本轮「已移植但不支持」可见性的样板。
2. 原有 9 条待路试项不变（terminal stop 斜率、无前车 terminal stop、AlwaysOnDM、Carrot 纵向源开关、
   Web Push 手机侧、视觉限速、天气、plannerd lead_index 硬证据）。
