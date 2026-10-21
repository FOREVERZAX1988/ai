# 上游 test 第 19 轮 — 信号灯的四个离线模块 / 保守绿灯 / 在线推理封装（2026-10-22）

范围：`upstream/test` 的 `8b52c4eef5..655d8d8466`（8 条，全部在 round 18 收口之后新增）。
**全部是离线工具 + 默认关的 opt-in**：不进控制路径、不加 Params 键、不碰 C++，所以
`libparams_c.so` 不用重建，Macan 手感不变（这一轮连 `feature_support` 门控都不需要）。

## 搬了什么

| 上游 | 内容 | 本仓 |
|---|---|---|
| `390bfc5419` | `MyMovingAverage`（replay harness 的依赖） | `openpilot/common/filter_simple.py` |
| `786b5de5db` | 参考几何 / 运动门 / 中央分组 / 上组试验 4 个离线模块 + 4 套测试 + start-group 场景测试 | `tools/signal_analysis/*`、`openpilot/sunnypilot/carrot/tests/test_signal_start_group.py` |
| `b906e9272b` | `conservative_green` 开关（绿光 hue 上限 105°→90°，排除青/黄光源）+ `replay_signal_central.py` | `tools/signal_analysis/signal_tracker.py`、`replay_signal_central.py` |
| `5053036159` | `process(..., allow_green=True)`：离线门否掉上下文时，绿票降级、确认绿回落、pending 清零；**红灯与时序不动** | 同上 |
| `a093896dc7` | 修 `allow_green` 块里被写成字面换行的转义 | 同文件（按最终状态搬） |
| `d37ff2c6da` | 修中央 replay harness 的未绑定 `load` 与半限定名 | 同文件（按最终状态搬） |
| `655d8d8466` | `neural_signal.py`（NV12 裁剪 + CPU ONNXRuntime / QCOM session + 后处理）+ 基准 | `tools/signal_analysis/neural_signal.py`、`benchmark_neural_signal.py` |
| `fda5f89907` | 把 MPC 终端软约束**钉在源码 + 一次真实求解**上（纯测试） | `openpilot/selfdrive/controls/tests/test_mpc_terminal_slack.py` |

一个批次内部有 3 条是「同一个文件的前后修正」（`b906→505→a093`、`b906→d37`），
所以按**最终文件状态**搬，而不是逐条打补丁——逐条打会在本树产生三次无意义的中间态。

## 为什么这一轮值得单独记

1. **`neural_signal` 的两个 ONNX 引用是用 sha256 钉死的，且不在任何仓库里。** 模块因此
   不可能「假装自己有真模型」：`_artifact()` 找不到文件就抛，任何一次实跑都只能喂本地替身。
   这是把「离线实验能不能相信」写成代码约束，而不是写在 README 里。
2. **保守绿灯是 opt-in，不是默认行为。** `SignalTracker(conservative_green=...)` 默认 `False`，
   车上唯一的调用方 `openpilot/selfdrive/modeld/signal_tracking_shadow.py` 与
   `sunnypilot/carrot/signal_assist.py` 都不传这个参数，所以在线路径逐字未变。
3. **`allow_green` 的语义是「只降绿、不动红」**：被剔除的上下文里红灯的获取与历史完全保留，
   因此它不可能缩短一次停车——这是这套实验能在车上被信任的前提。

## 顺手抓到的真 bug（本轮唯一一处生产代码外的缺陷）

`openpilot/common/tests/test_watchdog.py::test_a_stale_heartbeat_is_a_timeout` **在设备开机
不到 1 小时的窗口里必红**，而且是 `struct.error` 不是断言失败：

```
stale_ns = watchdog._now_ns() - int(3600 * 1e9)   # CLOCK_BOOTTIME 从开机算起
f.write(struct.pack("<Q", stale_ns))              # 开机 2086 s 时 stale_ns 为负
```

抓到时 `cat /proc/uptime` = `2086.25`，正好落在窗口内。它不是「偶发」：**每次重启后的头一小时
都会红**，而 round 17 那次记录「19 passed」只是因为当时设备已经跑了一小时以上。
修法保持意图不变——心跳的「多旧」按 uptime 缩放，阈值跟着缩放：

```python
now_ns = watchdog._now_ns()
stale_s = min(3600, max(1, int(now_ns / 1e9) // 2))
...
dt = watchdog.watchdog_timed_out(os.getpid(), stale_s / 10)
self.assertGreater(dt, stale_s * 0.9)
```

registry 里按 `mixed / expect_diff=true` 登记（`ours_keeps` 两条），phase 1 现在是 29/29。

## 验证

| 项目 | 结果 |
|---|---|
| `pytest tools/signal_analysis` | **121 passed, 4 skipped** |
| `test_signal_start_group.py` | **16 passed** |
| `test_mpc_terminal_slack.py` | **4 passed**（含 ON_DEVICE 的真求解：`solution_status=0`、`min(v_solution) >= -0.01`、`v_solution[1] >= 19`） |
| `pytest openpilot/common/tests` | **66 passed + 258 subtests**（修 watchdog 前是 1 failed） |
| `pytest openpilot/selfdrive/controls/lib` | **266 passed, 1 skipped**（= round 18 基线） |
| `pytest openpilot/sunnypilot/carrot/tests` | **786 passed, 6 skipped, 1 failed** —— 该条是 registry `known_issues` 里记的间歇项 |
| `ruff` | 改动/新增的 `openpilot/` 文件 0 新增；`tools/signal_analysis/` 沿用该目录既有口径（该目录本来就在 lint 门之外，例如 `signal_tracker.py` 既有 21 条） |
| `upstream_divergence_check.py --side worktree` | phase 1 **29/29**、phase 2 **1/1**、phase 3 **4/4** |

`4 skipped` 的 skip 理由变了，这本身就是 `390bfc5419` 生效的证据：
从「缺 `MyMovingAverage`」变成
`NameError: name '_ECO_FACTOR' is not defined` —— 那是 **harness 的边界**，不是本树的缺陷：
`_ECO_FACTOR` 在 `openpilot/sunnypilot/carrot/carrot_functions.py:104` 好好的，只是
`replay_signal_assist.py` 把 `CarrotPlanner` 类源码抠出来在合成命名空间里 exec，模块级常量不在里面。
这 4 条要真跑起来还得先补 cp 的 `signal_observation/signal_context` 钩子（见待办 31）。

## 没动的两条既有红（SCC 视觉闭环，`git stash` 摘掉本轮改动后同样红，故非本轮引入）

| 用例 | 根因 |
|---|---|
| `test_acceleration_is_continuous_through_planner_arbitration` | 夹具缺口：`longitudinal_planner.py:298` 现在无条件读 `sm['carStateSP']`（ICBM 门控），而这个测试的 `sm` 只有 `modelV2/carState/controlsState[/carControl]` → `KeyError: 'carStateSP'` |
| `test_nonurgent_activation_has_no_target_cliff` | 口径分歧：`v_target` 是按**进入阈值**反解的 —— `sqrt(1.8 / 0.03125) = 7.589`，测试期望的是模型自车速度 `8.0`。差 0.41 m/s，不是「悬崖」，但确实是「刚过阈值就先砍 5%」 |

两条都不在今晚这条同步链上，也不该在没有路试的情况下盲改控制行为，按待办留着。

## 下一轮

items 表已经空了（只剩 `0facf5cf71` agnos skip）。上游功能层清零，剩下的是三条**结构性问题**：
`upstream/test` 重基线（待办 7）、panda 指针 21 条（待办 25）、设备上跑不了整机 pytest 的基建缺口（待办 26）。
