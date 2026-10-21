# 上游搬运 第 15 轮（2026-10-21）

基线：本树 `sync/upstream-1019`，起点 `c313a42a96`（round 14 收口），终点 **`2d6e06b4b3`**。
round 14 收口时 `upstream/test` 停在 `4993c3cf32`。

## 1. 上游增量扫描

`git fetch upstream test`：`4993c3cf32 → 1b36f1ad36`，**1 个提交**。

| 上游 | 内容 | 体积 |
|---|---|---|
| `1b36f1ad36` | plannerd：lead-forecast 包装层收不下 MPC 的参数 | 2 文件 / +138 −5 |

### 扫描时踩到的一个坑（写进流程，避免下一轮重犯）

第一次统计时看到「上游 185 个提交（Aug 24 – Oct 17）」——这是**假的**。本机同时存在两个远端跟踪引用：

- `refs/remotes/mouxan/test`：旧远端 `mouxan` 删除后留下的**孤儿引用**，tip 是 `5f2ae96a64`（2026-10-17），早已 stale；
- `refs/remotes/upstream/test`：`git fetch upstream test` 真正更新的那个。

判据：`git ls-remote upstream test` = `1b36f1ad36`（ground truth）。孤儿引用与它不一致，而且和
`4993c3cf32` 无祖先关系（`merge-base` 落在 `09ffdf60fb`，即 registry 的 `base_commit`），
所以 `git rev-list --count 4993c3cf32..mouxan/test` 会算出 185，`git diff` 会算出「删了 34053 行」。
**以后一律 `git fetch upstream test` 后读 `upstream/test`，不读 `mouxan/test`。** 本轮已把孤儿引用删掉（`git update-ref -d refs/remotes/mouxan/test`，其 sha `5f2ae96a64` 记录在此行与登记表 `scope` 里，要查档案可按 sha 取）。

## 2. 这条提交与本树的真实差距

`1b36f1ad36` 讲的是上游那次事故：zoompilot 的包装层签名 `process_lead(self, lead)` 与 StarPilot 侧
MPC 的 `lead_index / model_lead / smooth_duplicate_vision` 对不上，`LongitudinalPlanner.__init__`
又无条件 `install()`，于是 plannerd 每一帧规划都 `TypeError`，整条链路无法 engage，offroad 自检却全绿。

本树 round 4 已经**吃过同一个 bug**，当时的本地补丁是让包装层 `**kwargs` 转发。逐字节比对确认，
本机与上游 pre-image 的唯一差异就是那三行：

```
-  def process_lead(self, lead) -> np.ndarray:
+  def process_lead(self, lead, **kwargs) -> np.ndarray:
+    # 045e473a33: ... forwards whatever it is handed.
-    lead_xv = self._upstream_process_lead(lead)
+    lead_xv = self._upstream_process_lead(lead, **kwargs)
```

也就是说本机 plannerd **没有崩**（round 4 已修），但上游这版还多两件事：

1. 接受**位置参数** `*args`（本机只收 keyword）；
2. **读 `lead_index`** 定位是哪条前车，只有拿不到时才回落到「按调用顺序计数」。本机一直是计数法——
   在当前 MPC（`lead_index=0` 然后 `=1`）下两者等价，但计数法依赖调用顺序这个隐含契约。

按「尽量与上游统一」的口径，本轮**整文件取上游**（`0cd5421b14`），本机那三行本地补丁被上游版取代——
上游版是它的超集，留两套只会在下次 rebase 再撞（round 14 的 `safe_mode_runtime._coerce` 同款教训）。
该文件内**没有任何车型分支或 Macan 适配**，取上游不触碰适配面。

## 3. 本树提交

| 本树 | 上游 | 内容 |
|---|---|---|
| `2d6e06b4b3` | `1b36f1ad36` | 包装层取上游（`*args` 转发 + 读 `lead_index`）+ 新增 `test_lead_forecast_process_lead.py` |

## 4. 这条提交真正值钱的是那条护栏

新增的 `openpilot/selfdrive/controls/lib/tests/test_lead_forecast_process_lead.py` 用 `ast` 读**两侧源码**、
两边都不 import，所以 PC 和车机都能跑。四个断言：

- MPC 里 `self.process_lead(...)` 恰好 2 处（leadOne / leadTwo）——「扫不到东西的护栏放行一切」；
- MPC 通过 keyword 传的每个参数名，包装层都收得下（命名参数或 `**kwargs`）；
- `install()` 仍然替换 `mpc.process_lead`，且包装层确实把 `*args/**kwargs` 转发给捕获的原始函数；
- 反证：把包装层写回 `def process_lead(self, lead)`，第二条必红。

这条护栏存在的理由本身就是个教训：`lead_forecast/tests/` 全是 pytest 且 import msgq，
**PC 没 msgq、车机没 pytest**，所以那批「68 个单测」从来没在任何地方执行过。上游也明说
`lead_forecast/tests/` 转 unittest 是「另一趟活」，本轮不碰，登记为待办。

## 5. 验证

- 新护栏：`python3 -m unittest openpilot.selfdrive.controls.lib.tests.test_lead_forecast_process_lead` **4/4 OK**。
- 回归：当初逼出这个 TypeError 的闭环用例
  `smart_cruise_control/tests/test_vision_controller_closed_loop.py` +
  `test_lead_duplicate_policy` + `test_model_lead_trajectory` **49 passed**。
- `ruff check` 两个文件 **All checks passed**。
- 无新 Param 键 → **不重建 `libparams_c.so`**；运行中进程不必重启（本轮改动在 plannerd，重启即生效，但不紧急）。

## 6. 登记表现状

`ported` 80 → 81；`items` 仍是 2 条且都不变：`63a6f3211b` NNFF（eval，等驾驶者拍板体积/延迟）、
`0facf5cf71` agnos 腾讯 cnb 镜像（skip，非 comma 硬件）。`upstream_tip` 更新为 `1b36f1ad36`。

## 7. 下一轮

- 转 `lead_forecast/tests/` 到 unittest（上游点名，本机同样从未执行）。
- 清理孤儿引用 `refs/remotes/mouxan/test`。
- 驾驶者侧待办不变：路试确认 CarrotTuning 页 `CustomKp=1.0` 手感、五个跟车档位行可存、
  `-O1 -g0` 峰值实测、terminal stop 斜率、AlwaysOnDM、`34f7b78b14` 开关、Web Push 手机侧。
