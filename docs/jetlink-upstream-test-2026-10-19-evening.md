# 上游 test 2026-10-19 晚：jetlink 优化对照 + 我们的进度存档

> 只读分析，未改任何工作区。数据源：`upstream/test` 新 tip `59efe220e6`（2026-10-19 17:43 +0800）、
> 我们的 `sp-macan-test` = `17deda2440`、`jetlink_repo` 我们 `7dfaa30` vs 上游 `39c555e`（其 cn tip）。

## 0. 一句话
上游 `test` 今天**强制重写了历史**（我们 10-17 合过的 `5f2ae96` 已不在新线上，merge-base 退回 `09ffdf60` 10-14），
净内容增量只有 26 文件 / +1903 −95；其中**最大的一项是 jetlink 的 lean-mici P0–P2 整体移植 + C3 venus 硬编 HEVC**，
正好是我们 skill 里排最后、风险最高的 3️⃣。双方在同一个 seam 上各做了 ~1100 行重构 → 真冲突。

## 1. 上游今天变了什么（内容口径，不是提交数）
- 23 个提交，但相对 `5f2ae96` 树的**真实增量 26 文件**。
- jetlink P0：`jetlink_adapter/hevc_venus.py`(+582) `tests/hevc_venus_check.py`(+470) `__init__.py`(+8)；
  `jetlink_repo` 9babbef → **39c555e**（其 cn tip，+86 提交）；`.gitmodules` 去掉 jetlink `branch=main`、panda `branch=master`。
- jetlink 侧 86 提交 = lean-mici P0–P2：`codecs.py`(166) `hevc.py`(343) `stream.py`(234 头门) `blend.py`(142)
  `latency.py`(127) `stages.py`(267) `hooks/events/models/state/testing`(+1252) `transport/aio+ffs`(+1068)
  `CHevc/jl_hevc.c`(364) + 全仓注释重写「say why, not when」（会让逻辑一致的文件也文本冲突）。
- 性能：radard_dpath arena 不再增长、softHold 期间暂停 DM、cereal 频率缓存、long_mpc 热路径。
- 修正：cruise 参数按注册默认值读；terminal-stop 双契约；`common/repo_tools.py` 按路径加载根 tools。
- opendbc +3（Mazda ON 从 ACC standby 重新武装 MADS、Oceania VIN 启动不崩）；**tinygrad 仍 `fe5d316`（与我们一致，指向 master，无变化）**。

## 2. 同题不同解
| 问题 | 上游 | 我们 |
|---|---|---|
| 弱 Wi-Fi 63 Mbit/s@20Hz | 砍字节：venus HEVC 393KB→~8KB（48×，有损，永不自动选） | 不动帧表示（raw/MED-zstd 无损，parity 0.99957 仍有效），只在时间上要余量 |
| 迟到判定 | `latency.py` 单比较 watermark（不调窗口） | 46ms 硬截止 + 5s 静默宽限 + 10/20 次计数 + 55ms 窗（全是调出来的数） |
| 六段计时 | capture/warp/send/reply_wait/publish/overhead，1200 槽(60s)，带分位进状态页 | pickup/warp/pair/encode/send/reply，64 槽，`jetlink: stages` 日志行（**验收脚本只认这个**） |
| 发现 | mDNS 限 wlan0 子网 + 记忆地址兜底 | 拨网关 + LAN 自动发现（无 mDNS 依赖） |
| 切换 | 10 帧交叉淡入 + 中点决策键 | 硬切 + 1s 证明期 + `in_control` 安全门（淡入应叠加，安全门不弃） |
| 保热 | venus 零 CPU → 20Hz 常发 | 小模型时不发帧（省 9ms）→ 冷启动短板 |

## 3. 冲突评估
- 超项目：**禁止 `git merge upstream/test`**。merge-base 被重写拉到 10-14，`merge-tree` 出 100+ 冲突且多为幻影（我们早已合过的旧内容）。
  正确做法：cherry-pick 26 文件增量（`52d31c1d70` `59efe220e6` `f45472b01b` `047f38d783` `c41a03695d` `d251c69946` + 测试修正），子模块指针手工收口。
- 真冲突 16 文件；其中**语义撞车**：`car/cruise.py`（我们 127/109 Macan 设定速度融合 vs 他们参数默认值重构）、
  `dmonitoringd.py`（我们 softHold 改动 vs 他们 softHold 期间暂停 DM —— 同一需求两套实现，必须二选一）、
  `radard_dpath.py`（都动 arena）、`jetlink_adapter/__init__.py`。
- 子模块 jetlink：我们改 168 / 他们改 237 / 重叠 140，6 个核心文件双方各改 ~1100 行；同路径新模块 15 个我们没有 → **几乎全冲突**。

## 4. 判定
- 帧表示/带宽层：**上游更好**（HEVC 是唯一让"上路+弱 Wi-Fi"结构性成立的方案）。
- 帧循环/降级策略层：**我们更好**（medium 决定帧循环、pipeline 不为自己等待、患者写、静默宽限；上游此层为空）。
- 诊断/切换体验层：**上游更好**（分位 stages 进状态页、单比较 lateness、淡入）；但我们的 log 行是验收依赖，迁移时保留。
- 结论：**他们的架构做骨、我们的策略做肉**；接入 HEVC/watermark 后要**退掉 55ms/1.5s 这类调参窗**，否则双重宽容掩盖真回归。

## 5. 我们的 jetlink 进度（2026-10-19 晚 snapshot）
- 1️⃣ 六段计时 ✅ 代码在设备（`caf0113`，设备上 tests/openpilot 76 passed；2 个 error 是 `/data/` 守卫，不是失败）。
  **真机验收未闭环**：当前 `latest.log` 无 jetlink 记录，`jetlink: stages` 0 命中。
- 2️⃣ 子网发现 ✅（`879d782`/`859796d`，是自动发现**不是** mDNS；上游现另有 mDNS 版）。
- 3️⃣ C4 venus HEVC ⛔ 我们没做 —— **上游 10-19 替我们做了**（`52d31c1d70`），这是本轮最大收获，不要再自造。
- 他们还有我们没有：头门 `stream.py`、watermark `latency.py`、淡入 `blend.py`、常发保热、hooks/events/models/state 分层。
- 我们还有他们没有：medium 帧循环、流水线、患者写、静默宽限、preview 落后帧 hold、Android/ORT/QNN 手机侧适配。
