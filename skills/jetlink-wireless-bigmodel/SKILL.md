# jetlink 无线大模型（手机 App 供算力）

**触发词**：jetlink、手机跑大模型、无线模式、行车预览、上路掉小模型、超时切小模型、Wi-Fi 断连、云端大模型

## 0. 先划边界：传输 vs 选型

- **传输面**（`jetlink/`、`wifi-lossless`、`joining.py`）只搬 warp 后的帧 `(2,6,128,256)` uint8 + packed scalars，**不含任何控制状态**。传输慢就查链路，别去动横向/纵向参数。
- **选型面**（用大模型还是小模型）在 `Params` 里。用户说"掉小模型"，先分清是**选型被回退**（lag/超时）还是**他手动切了**。

## 1. "家里预览好、上路就跑不起来"（历史根因，**已修** —— 不要再按它排查）

- **历史根因（2026-10-18 定案）**：preview 路径曾**独占**三条 Wi-Fi 救火改动：帧流水线(pipeline)、patient 写超时兜底、5 秒静默宽限。上路后 `IsOnroadPreview` 清零 → 三条全部失效 → 帧循环退回"**一帧在飞、等自己回包**"的串行形态；串行帧周期 45–56 ms 撞上 50 ms 相机周期 → **余量≈0** → 判 lag → `next attempt in 5 s` → 交回小模型。标志日志：`jetlink: in control, a preview's silence rule and its frame pipeline no longer apply`。**见到这行说明跑的是旧固件（< b8cbb92）。**
- **已修（证据在 `jetlink_repo`，按落地顺序）**：
  - `b8cbb92` openpilot: the medium decides the frame loop, not the preview —— 帧循环归属从 preview 挪到**承载介质**（`joining.py` ±20 行、`model_state.py` +123 行，配 `test_joining.py` / `test_model_state.py`）
  - `f09a8b7` the Wi-Fi hold window fits inside the camera's frame —— hold 窗口贴合 50 ms 相机帧，不再自我锯断
  - `a4e0d93` Wi-Fi 手机"落后一帧"是常态，不再每秒把大模型链路交还
  - `84de735` held 帧的迟到回包算作应答，不再误判 lost
- **排查起点因此前移**：先看六段计时（§5 第 1 项），不要再从 preview gate 起手。修后 preview 与 onroad 走**同一条**帧循环 —— 若仍出现"预览 7.7 ms / 上路 45–56 ms"这种落差，那本身是 bug 信号（介质判错或 hold 窗口被锯），不是模型设定问题。

## 2. 取证顺序（不要 cat 整个文件，不要连做三次 grep）

1. `grep_log` 搜 `jetlink: trips` → 结构化行：frames / held / pipelined / span_s / p50_ms / p99_ms / max_ms / server_ms，并算 hold_ratio、backlog。
2. **同一条链路取两段**（preview 段 vs onroad 段）对比：修后**两边都应是 pipelined、p50 同一量级**。
   - 健康：`frames 4401 held 0 pipelined 4401 p50 7.7 p99 8.6`
   - 异常：`p50 45–56`、`held` 上升、`pipelined` 归零 → 帧循环又被介质判错，回 §1 证据链查固件版本
3. `grep_log` 搜 `jetlink:` 看事件链：`in control, a preview's silence rule…`（仅旧固件）/ `modeld dropped x% of camera frames` / `next attempt in 5 s (failure N, link held Ns, drop N, lag N)` / `leaving (b…`。
4. 端到端分解口径（实测）：`p50 55.6 ms = warp 2.8 + data 0.7 + send 3.8 + wait 43.5`；服务端 `gpu 24–26 + queue 5–13`。**comma 侧只占 ~7 ms → C3 不是瓶颈**，不要建议换设备或降模型。
5. 怀疑丢帧：`read_manager_log` 看 modeld dropped 比例；秒级时间线用 `read_onroad_events`。

## 3. 判读阈值

| 项 | 值 |
|---|---|
| 相机周期 | 50 ms（20 Hz） |
| 帧周期安全线 | ≲45 ms（超过即零余量） |
| 硬截止 | 46 ms，超时发上一帧 hold |
| 回退判据 | 连续 5 次迟到 或 10 s 内 20 次 → 交回小模型；0.2 s 无回音 → lost |

## 4. 与上游对齐（fork-only 隐患先排）

- upstream remote **必须 HTTPS**，否则 `fetch` 假成功。
- 对重叠文件做**逐文件 patch-id 校验**，输出"上游改动是否仍生效"清单，而不是靠 commit 列表猜。
- 本技能相关分叉集中在：`jetlink/comma/wifi.py`、`jetlink/openpilot/model_state.py`、`joining.py`、`link.py`。

## 5. 优化路线（源自 lean-mici 对比，按**成本/收益**排序）

> 排序原则（2026-10-19 定）：**先纯增量遥测 → 再修"必然连不上"的发现逻辑 → 最后才动帧表示**（唯一有回归风险的一项）。下表 1️⃣→2️⃣→3️⃣ 即执行顺序。

**1️⃣（先做）C4 侧六段分段计时**（`frame_stages.h` 可直搬）
六段：取帧 → warp → 配对等待 → 硬编 → 发送 → 等 REPLY，64 槽环形缓冲按 frame_idx 索引，随 REPLY 报 `BigStageTimes`。落点 `link.py` + `status.py`。**纯增量、不碰控制、不碰 parity。** 现在只有服务端遥测、C4 侧空白 → 下次再断，分不清是 warp 慢、发送慢还是等回复慢，等于又回到靠猜。

**2️⃣ mDNS 服务发现（限 wlan0 子网）**
判据：接口必须 wlan0 + 解析 IP 必须落在 wlan0 的 IPv4 子网 + 连败 3 次重新发现，配手动 IP 兜底。当前 Wi-Fi 只拨默认网关，**手机是 peer 客户端（非网关）的 AP 场景必然连不上**。落点 `jetlink/comma/wifi.py`。

**3️⃣（最后做）C4 侧 venus 硬编 HEVC —— 只作为弱链路传输路径**
单帧 393,304 B → ~8 KB（**48×**），零 CPU（当前 Wi-Fi lossless 只 2.1×）。解开 `joining.py:33-38` 那个"发帧 9 ms/帧 → 饿死 DM 模型 → commIssue"的约束，从而可 20 Hz 常发 → 接管零冷启动。
必须**同时搬三样**：①序列头门（断档后首帧必须双路 IDR 对）；②配对前 warp + 10 ms 容差配对；③MetaCache 查不到**不弹队**（弹空全队会吃掉新序列的双路 IDR）。
**风险**：有损 → 输出不再 bit-for-bit，**parity gate 0.99957 失效**。做成**双模式**：USB 3 保持原始帧保 parity，弱链路才用 HEVC；上线前用 route 回放做 A/B。

**排在 3️⃣ 之后（体验类）**
- 切换期**全头交叉淡入**：10 帧（0.5 s）线性淡入 + 兜底帧 hold 最近大模型输出，替代硬切。两模型规划路径差 ~195 m，硬切突兀。**但不可因此放弃 `in_control` 门**。
- REPLY 迟到判定 **`_gave_up_t_eof` 归零法**：一行判定替代计数窗口。硬截止仍用 jetlink 双窗口（更严），迟到统计用归零法（更简）。
- 工程治理：特性做完反手清死代码；注释即权威 + 票号溯源。

## 6. 硬约束

- **不在控车时切换**大小模型（`in_control` 门是安全设计，不是可以拿来换平顺性的东西）。
- **不假设 bit-for-bit parity**：一旦引入有损编码，parity gate 结论作废，必须重新量化。
- **不动 panda 子模块**（会造成 tizi 设备报错）。
- **发布闭环**：修代码 → 先看 CI（如 `853c4ca` 那两条 build 失败）→ 打 APK release → 用户手机重装。**补了提交 ≠ 有新 APK**，回答"apk 要不要重下"必须给 release tag 链接和版本号。

## 7. 证据文档

- 全文（路径+行号级证据）：`ai/docs/jetlink-vs-lean-mici-2026-10-19.md`
- 原始上传：`/data/media/lean_mici_vs_jetlink_2026-10-19.md`
- 历史排查记录（同一台 tizi / 同一链路）：`ai/docs/JETLINK_PIPELINE_1016.md`（8e6 的三处串行）、`ai/docs/JETLINK_WIFI_FPS_1016.md`（帧预算）、`ai/docs/JETLINK_WIFI_PIPELINE_1017.md`（B/D/C 落地，含"响应只有 8,292 B，压缩收益 <1%"的结论 —— **不要再提响应压缩方案**）
- 上游：`https://github.com/mouxangithub/jetlink`（无线模式亦在本仓库 preview/wifi 路径，不在别的分支）
