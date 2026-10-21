# 上游 test 第 7 轮 — 模型 picker 的本地体积台账（2026-10-21）

范围：`4630b96a77`（`models: local size ledger so the picker can see what is on disk`）。
**纯 UI 文案 + 只读 stat**，不进控制路径、不加 Params 键、不动 C++，所以
`libparams_c.so` 不用重建，Macan 也不需要任何 `feature_support` 门控（这条与车辆无关）。

## 为什么要它

picker 过去只能通过 `manager` 的下载进度描述一个 bundle——进度只存在于「正在下」的那段时间。
一次被中断的下载、或者很久以前选好的 bundle，行上什么都没有。台账改成回答**本机磁盘有什么**：

| 磁盘状态 | 行上显示 |
|---|---|
| 完整文件 / 完整 chunk 集 | `downloaded` |
| 下到一半的 chunk 集 | `42% on disk` |
| 什么都没有 | 什么都不显示（大模型行走 jetlink 的 `ready on Jetson` 口径不变） |

没有 HEAD 请求、没有哈希、没有任何写操作：`stat()` only，外面套 2 s 有界缓存，
所以滚动时每帧重渲染不会去重扫模型目录。

## 搬了什么

| 上游 | 本仓 | 内容 |
|---|---|---|
| `4630b96a77` | 本轮 | 新增 `openpilot/sunnypilot/models/model_sizes.py`（179 行）+ 21 条单测；`model_info.local_model_note()`；`models.py` 的 `_bundle_to_node` 接线 |

`sp` 的 Artifact schema 没有声明字节数，所以百分比退化成「已下 chunk 数 / manifest 声明的 chunk 数」——
chunk 是定长的，这个近似是诚实的；磁盘上一个字节都没有时返回 `None` 而不是 `0%`，行上就不显示，
免得把「没下过」说成「下了 0%」。

## 与上游的刻意分歧

`models.py` 的 `model_info` import 块本树更长：`active_source`、`standin_model` 在本树也从
`model_info` 取（上游从 `accelerator_link` 取），所以这条没走 `cherry-pick`，是按本机 import 块手工并的。
接线点 `_bundle_to_node` 与上游逐字一致。已记进 registry 的 `expect_diff_after`。

## 验证

- `openpilot/sunnypilot/models/tests/test_model_sizes.py`：**21 passed**
  - 其中 `test_it_matches_file_chunker_exactly` 是跨模块断言：台账的 `chunk_file_name`
    必须与 `common/file_chunker.get_chunk_name` 逐字相等，跑的是本树真模块，
    以后任何一边改命名都立刻红
- `ruff`：4 个改动文件 **0 新增**（`models.py` 的 4 条 F401 / ISC002 / E501 与 `HEAD` 版本
  用 `--stdin-filename` 复核后逐条一致，行号仅因 import 多一行而 +2）
- `py_compile`：三个 py 文件均通过
- `upstream_divergence_check.py --side worktree --pending-only`：phase 2 **8/8**、phase 3 **4/4**

## 下一步（items 剩 8 条）

- `93b695da88`（雷达点叠加档位）——本树没有 `ShowRadarInfo`，按「不支持就把 UI 变灰默认关」的口径
  可以顺势做成一个正面例子
- `0ba6c81d04`（大 UI 补 Rear Camera 一节 + SLA 去重 + 中文）——参数本机已有，只缺入口
- `7fd88d270b` + `aab6ed90f8`（watchdog，C++ 新目标，两个 commit 一起才成立）
- `dbe9c7c52c`（SLC 限速突降的舒适松弛 + safe-mode stock 语义）——第 6 轮之后才有 stock 语义可用
- `eval` 三条：`d81eec5899`（视觉限速，2883 行 + 22MB）、`63a6f3211b`（NNFF，127 文件）、
  `d4136d1df0`（依赖 `d81eec5899`）
