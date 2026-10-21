# 上游 test 第 20 轮 — 神经观测 worker 接线 + 替身模型仿真（2026-10-22）

范围：`upstream/test` 的 `655d8d8466..30d93e8093`（1 条，round 19 收口后新增）。
父仓提交 `4f011c85c9`。

## 搬了什么

| 上游 | 内容 | 本仓 |
|---|---|---|
| `30d93e8093` | `signal_neural_shadow.run_auto`：每轮重算 backend，`auto` 在 QCOM 与 CPU 相机跟踪之间**跨进程**切换（`spawn` + terminate/kill/join，换模式即释放 GPU 缓冲） | `openpilot/selfdrive/modeld/signal_neural_shadow.py` |
| 同上 | `signal_tracking_shadow.run(..., comparison_override=...)`：让 CPU 分支能被同一个选择器驱动 | 同文件，**搬完与上游逐字节一致** |
| 同上 | `make_substitute_models.py`：按真实契约生成常量输出 ONNX | `tools/signal_analysis/make_substitute_models.py` |
| 同上 | `sim_neural_on_c3.py`：NV12 裁剪 → detect → classify → sequence 的整链仿真 | `tools/signal_analysis/sim_neural_on_c3.py` |

这一轮仍然**零 Params 新键、零 C++、不进控制路径**，`libparams_c.so` 不用重建；
`/data/signal-color-shadow` 在本机根本不存在，模块 `requested()` 一律为假，所以在线行为逐字未变。

## 跑起来才抓到的两个缺陷

### 1. `automatic_backend()` 会打崩 auto worker（生产代码）

上游用四个裸 `params.get_bool(...)`：

```python
dm_needed = (params.get_bool('DriverMonitoringEnabled') and
             not params.get_bool('DriverMonitoringSessionDisabled')) or params.get_bool('IsDriverViewEnabled')
```

本树 `params_keys.h` 里**没有** `DriverMonitoringSessionDisabled`（我们没有 DM session 概念），
而 `Params.get_bool` 对未注册键抛 `UnknownKeyName` —— 不是返回 False。于是 auto 模式第一次
循环就抛，worker 直接死，不是「选错后端」。

实测确认（设备上直接 `Params().get_bool('DriverMonitoringSessionDisabled')` → `UnknownKeyName`）。
四个读全部改走 `sunnypilot/common/param_read.read_bool`，缺失默认 `False` = 上游语义里的
「session 未禁用」；另三个键本树本来就有，读法等价。

### 2. `test_modeld_keeps_original_artifact_and_output` 永远不可能通过（测试）

它断言 modeld.py 里存在 `self.npy['prev_feat'][:] = model_output[...]`。那行在
上游 #38916（history queues 移进 ONNX）之后就不存在了，本树跟的是新版 modeld.py，
所以这条断言是「不可能通过」，不是「保护」—— 每次跑 `openpilot/selfdrive/modeld/tests`
都红，而 round 19 的验收清单里没有这个目录，于是它一直没人看见。

改成钉住那行本来想表达的不变量：capture 在原始输出之后、`parse_outputs` 之前；
`_signal_shadow` 在填 modelV2 之前被 pop 掉。

## 仿真（真跑，不是纸面）

> **2026-10-22 06:5x 补充（驾驶者拍板后落地）**：这些依赖已从 `/data/tmp/nn_deps`（115 MB，靠 PYTHONPATH 临时挂）
> 并入永久目录 `/data/.pydeps`（顶层目录名与已有包零重叠），源目录已删。现在 `python3 tools/signal_analysis/sim_neural_on_c3.py`
> **不用任何 PYTHONPATH 前缀**就能跑（1.7 s，输出与本节记录逐项一致）。完整配方见 `ai/docs/neural_sim_recipe.md`。

设备上没有 `onnx`/`onnxruntime`，装在 `/data/tmp/nn_deps`（`--no-deps --target`，
借用系统 numpy 2.5.1 / cv2 4.13，`PYTHONPATH=/data/tmp/nn_deps:/data/.pydeps:/data/openpilot`）。
注意两点，否则跑不起来：①`pip` 的 `TMPDIR` 默认是 150 MB 的 tmpfs，会 `No space left`
（用 `TMPDIR=/data/tmp/pipwork`）；②设了 `PYTHONPATH` 后 `site-packages` 里那两条
`.pth` 路径（`/data/openpilot`、`/data/.pydeps`）不再进 `sys.path`，必须手工补。

```
nv12_crop        (760, 1344, 3) uint8；三种坏几何全部 rejected: invalid NV12 crop geometry
detect           1 box [646.2, 491.1, 723.7, 568.6] score 0.902
classify         red 4.0（原始 logit）; 空 crop -> unknown 0.0
sequence_first   1 track，100 ms 后仍在
```

除两个权重文件外全是真代码：NV12 裁剪、letterbox 416、session 创建、score 乘积、网格解码、
NMS、224 裁剪 + ImageNet 归一化、label 查表。sha256 的 pin 只在仿真里被替换，
wrapper 里一次都没放松——这是「跑得起来的模型一定是替身」这条约束的落点。

## 验证

| 项目 | 结果 |
|---|---|
| `pytest openpilot/selfdrive/modeld/tests openpilot/common/tests` | **109 passed + 258 subtests**（修 modeld 那条前是 1 failed） |
| `pytest tools/signal_analysis` | **121 passed, 4 skipped** |
| `test_signal_start_group.py` | **16 passed** |
| `pytest openpilot/selfdrive/controls/lib` + `test_mpc_terminal_slack.py` | **270 passed, 1 skipped** |
| `test_following_distance.py`（闭环仿真，266 s） | **18 passed, 1 skipped** |
| `controls/tests` 其余 12 个文件 | 全绿；`test_leads.py` 仍挂（round 17 已记：真起 `card` 子进程等在那里） |
| `pytest openpilot/sunnypilot/carrot/tests` | **787 passed, 6 skipped**（round 19 记的间歇红这次没出现） |
| Macan 侧 | `test_platform_configs -k MACAN` 1 passed、`test_macan_radar_fusion` 10 passed、`test_vcruise_pcm_set_speed` 6 passed |
| `ruff` | 新文件全绿；`signal_neural_shadow.py` 与两个 shadow 老文件同口径（`C408/E702/RUF100`，pyproject 里逐条登记） |
| `upstream_divergence_check.py --side worktree` | phase 1 **30/30**、phase 2 **1/1**、phase 3 **4/4** |

## 下一轮

`items` 还是只剩 `0facf5cf71`（agnos，skip）。上游 `test` 的功能层已清零，剩下的仍是三条结构性问题：
重基线（待办 7）、panda 指针 21 条（待办 25）、设备上跑不了整机 pytest（待办 26）。
本轮又给待办 26 添了一条实证：**一个从未被任何验收清单覆盖的测试目录里躺着一条永远红的断言**，
而它不是靠读代码发现的，是靠把整目录跑了一遍。

## 顺带复核：10-19 的 jetlink 无线优化没被后面的合并吃掉

驾驶者 10-21 报「行车预览下 Wi-Fi jetlink 完全稳不住，是不是合并把优化弄没了」。按 10-19 那支
DAY_LOG 的五条修复逐条验（证据是 git 祖先关系，不是回忆）：

| 修复 | 现在还在吗 |
|---|---|
| `a4e0d93` Wi-Fi 落后一帧不再每秒交还大模型 | **在**（jetlink 指针 `3ffb61f` 的祖先） |
| `84de735` 被 hold 帧的迟到答复由下一帧读走 | **在** |
| `904e041` stop 信号由 handler 接管（0.8.7-1019-1） | **在** |
| `f09a8b7` Wi-Fi hold 窗口收回相机帧内 | **在** |
| `b8cbb92` 帧循环由介质决定，不再由 preview 决定 | **在** |

代码层面也对得上：`WIFI_HOLD_FRAME 0.046 / WIFI_SETTLING_FRAMES 8 / WIFI_HOLDS_ALLOWED 150`
仍在 `jetlink/openpilot/model_state.py`，并且在 `joining.py:932` **按介质**注入；剩下的
`IsOnroadPreview` 只出现在注释与声明里，不再是流水线的开关。父仓侧钉住这五条的
`ae4e66ce80`（`sp-macantest-1018`）也是当前 HEAD 的祖先。

所以 10-21 那次不稳**不是**合并丢代码。要定位得靠下一次上路的 swaglog（`p50/p99`、`held`、
`drop %`、`lag N this drive` 那几行），本机 ignition=false、jetlink 不跑，offroad 复现不了。
