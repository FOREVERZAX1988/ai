# 8 条未移植：每条到底卡在谁身上（2026-10-24 复跑）

> 复跑：`python3 ai/scripts/upstream_divergence_check.py --pending-only`
> 结果：phase 1 `32/32 as expected` · phase 2 `8/8 still unported（可搬 0 · 被阻塞 8 · DRIFT 0）` · phase 3 `4/4 consistent`
> 上游 `upstream/test = 684178cb51`（`git fetch upstream test` 无新对象，registry 的 scope 仍成立）。

## 0. 为什么这次要加 blocked_by

旧口径下 phase 2 只回答一个问题：**「搬了没」**（探针还在不在）。于是「还剩 8 条待搬」被读成
「8 份工作量」。实际上探针成立完全不等于今天能动手：其中 4 条只能跟子模块指针一起走、
2 条要驾驶者先定产品语义、2 条是依赖项（它们描述的对象在本树里根本不存在）。

于是本轮给每条 item 加了机器判定的 `blocked_by = {kind, reason, ref?}`，`kind` 四选一：

| kind | 含义 | 解除方式 |
|---|---|---|
| `driver-decision` | 产品语义 / 上车才敢定 | 驾驶者一句话 |
| `submodule-pin` | 只能跟子模块指针一起动 | 指针 bump + 上车验证一轮 |
| `dependency` | 需要本表另一条先落地（`ref` 指过去） | 被依赖那条先动 |
| `no-port` | 上游自有 housekeeping，无内容可搬 | 不需要动作，只留档 |

checker 现在把 phase 2 分成「可搬 / 被阻塞 / DRIFT」三堆，并对注释做自洽校验：
未知 kind、`dependency` 不带 `ref`、`ref` 指到表外、**依赖链断在半路**（被依赖那条自己已经
没有阻塞 = 这条其实能搬了，表过期）、非 `dependency` 却带 `ref` —— 全部 FAIL。
用例：`ai/tests/test_upstream_divergence_blockers.py`（8 passed，含真实登记表自洽断言）。

## 1. 逐条：卡在哪

| # | 上游提交 | 主题 | 阻塞 | 具体卡点 / 解除条件 |
|---|---|---|---|---|
| 1 | `eeb028a58` | panda: 适配c3（21 条：UART 移除、certs 挪 crypto/、F4 build） | `driver-decision` | 含 safety/UART 结构变化；纪律是 tizi 设备 panda 不动。需拍板 + 上车验证一轮 |
| 2 | `ee23033248` | 更新（AGENTS-memory + opendbc 指针 b9e3f006 → 52ab0722） | `submodule-pin` | 指针含 `vCluRatio`/`speedLimitDistance`/`logCarrot` 字段；子模块只能上车验证后动 |
| 3 | `e3cf1856c9` | 更新（同上目标 pin 的空壳提交） | `submodule-pin` | 随 #2 走，不单独动作 |
| 4 | `7ed16d83a6` | feat(xiaoge): YOLO obstacle head（inference/server wiring/carStateSP） | `driver-decision` | 新增 `yolo_inference.py` 345 行 + 接线 + 模型资产；要不要这条路是产品决策 |
| 5 | `67ffbe9f03` | xiaoge: cp 三分类 BSD 分类器 + 双侧连续监控 | `driver-decision` | 540 行，且 `OnnxBsdThreshold` 默认 45 → 94 改的是盲区语义，需驾驶者定 |
| 6 | `f1751249ae` | docs(xiaoge): 两套 YOLO 检测器为何共存 | `dependency` → `7ed16d83a6` | 实测本树 `sunnypilot/carrot/xiaoge/` 只有 V-ASM 一套（无 `yolo_inference.py`），注释的对象不存在，单独搬是无主注释 |
| 7 | `1e97bf13a9` | test(capnp): 盲区 split 字段钉在 @75-79 | `dependency` → `ee23033248` | 钉的 `leftBlindspotOem`/`rightBlindspotOem` 由 opendbc 52ab0722 引入；本树 opendbc `b9e3f006` 的 `car.capnp` 里 grep 为空，测试无处可钉 |
| 8 | `564e8e93c8` | merge: pull the test branch onto zoompilot's develop | `no-port` | 上游自己的 rebase 基座合并（1687 文件），只承载 panda/opendbc 两个指针 |

**结论：现阶段「可搬」是 0 条。** 剩下 8 条全部落在三种先决条件上：panda/opendbc 指针（3 条）、
产品拍板（2 条，YOLO 障碍物头 / 三分类 BSD）、以及被前两者带走的依赖项（2 条）+ 1 条留档。

## 2. 想推进的话，只有两条真实路径

1. **指针批**（#1/#2/#3 一起）：panda `d84b110fc → eeb028a58` + opendbc `b9e3f006 → 52ab0722`。
   这两条一旦上车，`1e97bf13a9` 的 capnp 钉字段用例也随之可写。#7 于是自动解锁。
   风险在 safety/UART 结构变化，必须一轮低速实车验证，不能只看 offroad。
2. **xiaoge 视觉批**（#4/#5 + 随行的 #6）：YOLO 障碍物头 + 三分类 BSD。要先确认模型资产
   （ONNX 权重）与后端（QCOM/CPU）是否已经在设备上，否则搬了也是空跑。

两条都不是「今天顺手搬完」的量级，且都要求驾驶者在场或明确授权。offroad 阶段能做的只有
记录、探针、注释这三件，本轮已做尽。

## 3. 推送状态（本轮核对）

| 项 | 值 |
|---|---|
| 父仓 HEAD | `b37b818cdf` |
| 父仓远端 `origin/sp-macan-test3` | `b37b818cdf`（一致，已推完） |
| `origin/sync/upstream-1024` | **不存在**（本地分支从未建远端同名分支；远端只有 `sync/upstream-1019`） |
| ai 子模块 | 分支 `sp-macan-test2`，本文与 checker 改动随指针 bump 一起推 |
