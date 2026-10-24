# opendbc pin 52ab0722：内容等价，不动指针（2026-10-24 实测）

> 一句话结论：把上游 pin `52ab0722` 三方合并进本树 opendbc `2abfa684`，**工作树净改动为 0**。
> 这条不是「待搬」，是「早就等价存在、只是历史不同源」。登记表按探针判它是未移植，是探针口径的局限。

## 1. 怎么判的（可复跑）

```bash
cd /data/openpilot/opendbc_repo
git worktree add -f /data/tmp/odb-pin -b pin-52ab0722 HEAD
cd /data/tmp/odb-pin
git merge --no-ff --no-commit 52ab072204b58be9ad8f540a5b2bb5003a2f3afe
git status --porcelain          # 期望：空
git diff --stat HEAD            # 期望：空
```

实际结果：`git status --porcelain` 为空、`git diff --stat HEAD` 为空 ⇒ pin 的树内容与我们的头**逐字节等价**。

## 2. 中间那个坑：car.capnp 自动合并把 @62-74 重复了一份

第一次合并后 `opendbc/car/car.capnp` 里 `pcmCruiseGap @62` … `logCarrot @74` 整整出现了**两遍**。
原因：pin 侧（`8c12b1236` / `a8b81c552` / `52ab0722`）与本树（`2abfa684`）**在同一位置插入了同一块字段**，
git 认为两侧各插一次互不冲突，于是文本上出现两份 —— capnp 会直接报重复 ordinal。

判据：把该文件回退成 HEAD 版本后净改动为 0，说明**两份内容一模一样**，重复纯属三方合并的记账产物，
不是真的多了一组字段。

核对 CarState 顶层字段（脚本内含，排除嵌套 struct 的 ordinal 干扰）：
70 个顶层字段、最大 ordinal `@79`、**无重复 ordinal**、尾部是
`logCarrot @74 / leftBlindspotOem @75 / rightBlindspotOem @76 / leftBlindspotOnnx @77 / rightBlindspotOnnx @78 / blindspotSplitSourcesValid @79`。
（`@0/3/5/12/13/19/28/29/46/49` 的空洞是 baseline 本来就有的，来自 union group，不是本轮引入。）

## 3. 为什么 `git cherry` 还报 2 条「没打」

```
git cherry -v HEAD 52ab0722
- a3c88c85e 适配c3                              # 已打（同 patch-id）
- 8c12b1236 car: expose vCluRatio/...           # 已打
+ a8b81c552 car: add source-aware blindspot...  # patch-id 不同 ⇒ 报「没打」
+ 52ab0722  car: fix blindspot split ordinals   # patch-id 不同 ⇒ 报「没打」
```

本树 `2abfa684`「car: CarState 追加盲区来源拆分字段 @75-79」**一条提交同时承载了** pin 的
「加 5 个字段」+「ordinal 必须落在 @75-79（cp 的 @95-99 抄不得）」，patch-id 自然对不上，
但树的最终状态相同。所以 `+` 这两条是**记账差异，不是内容差异**。

## 4. 为什么不顺手把指针搬过去

- 本树 opendbc 领先 pin **284 条独占提交**（Mazda/MADS/CarParams 等），只能 merge 不能 FF；
- merge 的结果既然与本树逐字节相同，搬指针的唯一效果是**把 284 条提交挂到一个不通源的父提交上**，
  给下一次 rebase 增加面，收益 0；
- 真需求（capnp 字段、vCluRatio/speedLimitDistance/logCarrot、BSD 拆分字段）本树都已有。

结论：**opendbc 指针保持 `2abfa684`**。以后上游再动 opendbc pin，先跑 §1 那条判据：
净改动 0 就继续留在 `merged_in`，别再当待办重开。

## 5. 连带影响

- 登记表 `upstream_pending_port.items`：8 → 6（YOLO 头 / 两套检测器 docs / capnp 契约守卫）→ 4（三分类 BSD）
  → **本轮 2 条**（`ee23033248` 指针 + `e3cf1856c9` 空壳）移入 `merged_in`，**剩 2 条**：
  `eeb028a58`（panda 指针，真补丁 20 条）+ `564e8e93c8`（上游 rebase 基座合并，无内容可搬）。
- `1e97bf13a9`（capnp 契约守卫钉 @75-79）已在 `1c5f093394` 落地，它对 opendbc pin 的依赖**随之解除**。
