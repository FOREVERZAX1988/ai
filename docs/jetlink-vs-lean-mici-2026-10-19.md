# lean-mici vs jetlink：外接算力跑大模型的两条路线

**分析日期**：2026-10-19
**lean-mici**：`https://github.com/lochuan/lean-mici`，分支 `lean-master`，HEAD `8a8e9459a`（AGNOS 19.6.29）
**jetlink**：`E:\sp\jetlink_repo`，API 3，协议 v3
**证据口径**：全部结论附文件路径与行号，无推测

---

## 结论先行

1. **是的，lean-mici 确实有与 jetlink 完全对位的"车机 → 外接算力端跑大模型"链路**，且有两条腿：`openpilot/selfdrive/bigmodeld/`（C4 侧 C++ 上行进程，3492 行代码 + 1605 行宿主测试）与 `openpilot/system/lanlinkd/`（局域网版 sunnylink，2172 行 Python）。服务端是 Android App「Chipmunk」（不在本仓库，走手机 NPU/QNN 跑约 1B 模型，源项目 `1b-model-qnn`，见 `bigmodeld/README.md:129`）。

2. **两者模型输入语义完全一致，但传输表示根本不同**。两边都送 openpilot 标准 warp 输出 `(2, 6, 128, 256)` uint8（road + wide，各 196,608 B）：
   - jetlink 传**原始 393,304 B**（`docs/link-protocol.md:30-32`），USB 3 上不压缩
   - lean-mici 传 **C4 侧 venus 硬编 HEVC 后的 ~8 KB**（`bigmodeld/README.md:6-8`，两路各 4 KB @2 Mb/s/路）

   压缩比约 **48:1**，代价是**有损**。这一条差异决定了后面所有架构分歧。

3. **哪个好：分场景，不是同一个问题**。jetlink 在工程成熟度、平台广度、模型生命周期、安全回退上全面领先；lean-mici 在"零外设、无线、用现成手机 NPU"这个产品形态上有独特工程优化，其中 **①C4 侧硬件编码** 与 **②20 Hz 常发保持大模型热状态** 两条，恰好补上 jetlink 当前的两个明确短板。

4. **jetlink 值得借鉴 5 条**，按价值排序见文末「借鉴清单」。

---

## 一、路线对比总表

| 维度 | lean-mici | jetlink (E:\sp) | 证据 |
|---|---|---|---|
| **链路** | **Wi-Fi/LAN TCP**（手机热点或 AP） | **USB 3 有线为主**（vendor bulk）；Wi-Fi 为次选 | `bigmodeld/main.cc:4`；`docs/link-protocol.md:88-90` |
| **帧传输表示** | C4 venus **HEVC 硬编**（Main/VBR/无B帧/GOP20/2 Mb/s/路） | **原始 uint8**（USB）；Wi-Fi 时 **MED+zstd 无损**（2.1×） | `bigmodeld/README.md:6-8`；`docs/link-protocol.md:47-53` |
| **单帧线长** | road ~4 KB + wide ~4 KB = **~8 KB** | **393,304 B**（USB 补零到 409,600） | `main.cc:69`；`link-protocol.md:30-32` |
| **warp 位置** | C4 CPU/NEON 查找表（0.32 ms/路） | C4 GPU tinygrad JIT | `warp_pack.h:56-59`；`jetlink/openpilot/warp.py:1-14` |
| **服务端算力** | 手机 NPU（骁龙 QNN），~1B 模型 | Jetson TensorRT / Mac ANE+GPU / iPhone CoreML / Android QNN / PC | `bigmodeld/README.md:129`；`docs/backends.md:8-16` |
| **服务端实现** | Android App「Chipmunk」（**不在本仓库**） | **统一 Swift 服务端**（开源，本仓库） | `bigmodeld/README.md:8,14`；`docs/backends.md:1-3` |
| **服务发现** | **mDNS `_bigmodel._tcp` 限 wlan0 子网** + 手动 IP 兜底 | USB 枚举；Wi-Fi 拨默认网关 + PEER_FILE 缓存 | `server_locator.h:4-9`；`jetlink/comma/wifi.py:12-14,37-38` |
| **上行时机** | **20 Hz 常发**（保持大模型热状态） | **仅大模型接管后发**（小模型时不发，省 9 ms/帧） | `big_model.py:1-4`；`jetlink/openpilot/joining.py:33-38` |
| **超时策略** | 结果一到就发，**不等截止**；迟到只计数 | **46 ms 硬截止**，超时发上一帧（hold） | `big_model.py:171-192`；`link-protocol.md:24-29` |
| **切换方式** | **全头交叉淡入 10 帧**（0.5 s），兜底帧 hold 最近大模型输出 | 硬切（历史重置）+ 1 s 证明期 + `in_control` 门 | `big_model.py:76-103`；`joining.py:22-31,40-47` |
| **回退判据** | 5 次连续迟到 / 10 s 内 20 次 → 交回小模型 | 同（behind）；0.2 s 无回音 → lost | `link-protocol.md:24-29`；`big_model.py:114-122` |
| **状态暴露** | Param `BigmodelLinkState`（connecting/connected/**blip**/**restart**/lost） | 结构化 `Status` 对象给 UI | `uplink_sender.h:175-195`；`openpilot/__init__.py:106-110` |
| **隐藏状态归属** | **服务端**（C4 侧裁掉 hidden_state） | **服务端**（v3 起，回复 72 KB → 8 KB） | `big_model.py:4`；`protocol.py:24-28` |
| **分段计时** | **C4 六段环形槽**随 REPLY 上报（BigStageTimes） | 服务端遥测 gpu/queue/total_us；C4 侧无等价物 | `frame_stages.h:3-8`；`protocol.py:115-118` |
| **安全/鉴权** | HELLO 带 instance_id 区分重启/闪断；**HMAC 已撤销**（ADR-0003） | API 版本闸 + 适配器契约；无鉴权 | `frame_codec.h:180-183`；`openpilot/__init__.py:14-28` |
| **代码量** | bigmodeld 3.5 k C++ + lanlinkd 2.2 k Py | jetlink 11.8 k Py + Android 7.6 k + Swift 8.9 k | 实测统计 |

---

## 二、lean-mici 值得学习的点（附代码级证据）

### 2.1 【最有价值】C4 侧硬件编码：用 venus 换 48× 带宽，且不吃 CPU

lean-mici 把压缩放在 C4 的 **venus 硬件编码器**上，而不是 CPU 软件压缩：

> `bigmodeld/README.md:5-8`：用 `logger_lib` 的 `V4LEncoder` 双路硬编（HEVC Main、VBR、无 B 帧、GOP 20、venus realtime 优先级、默认每路 2 Mb/s 可调）
> `main.cc:69`：`constexpr int kDefaultBitrate = 2'000'000;  // 2 Mb/s/路（512×256 下约 4 KB/帧/路）`

工程细节也做得干净：
- **编码前按 `timestamp_sof` 配对**（10 ms 容差），未配对死亡帧只计数不中断码流（`README.md:29-33`）——双路码流不会因单路缺帧撕裂
- **不建 PubMaster ⇒ loggerd 无编码数据**（`README.md:7-8`），编码流不进落盘链路，零副作用
- **码率运行时可变**：`Params "BigmodelEncoderBitrate"` 每帧读（`main.cc:620-630`）
- CPU 亲和明确：取帧线程 road→core 2 / wide→core 6，刻意避开 core 4/5（control/ui）与 core 7（modeld）（`README.md:30`）

**为什么这对 jetlink 重要**：jetlink 明确因为 CPU 成本而不敢常发帧——

> `jetlink/openpilot/joining.py:33-38`：**No frames go to the host while the small model drives.** Sending them costs the comma ~9 ms of every frame ... which starves the driver monitoring model under selfdrived's frequency floor (commIssue).

这 9 ms 是 **warp + 393 KB 搬运** 的 CPU 成本。如果换成 venus 硬编（零 CPU），这个成本消失，就能像 lean-mici 一样 20 Hz 常发保热状态。

### 2.2 20 Hz 常发保持大模型热状态 → 接管零冷启动

> `big_model.py:114-126`：`BigReplyLatch` 读线程独立于 `model.run()`；`warmup_replies` 处理"手机新建序列后头 N 个 REPLY 不用"

配合常发，大模型的时序状态（queue / hidden state）在接管瞬间已是**热的**，接管无冷启动。

对照 jetlink：小模型驾驶时"link idles on a keepalive ping"（`joining.py:22-23`），接管时"The large model is built on the swap frame and **starts from a reset history**"（`joining.py:24-25`）。**这是 jetlink 明确的体验短板**——冷启动历史意味着接管后头几帧质量不可靠，才有那个 1 s 证明期。

### 2.3 序列头门（Head Gate）：断档后首帧强制双路 IDR 对

> `uplink_sender.h:14-19`：连接建立、截断重连、码流断档之后，第一个发出的帧必须是「预测双 IDR + 实测双 IDR」对；不合格对整对丢弃（kHeadBarrier）

这是视频流的严谨恢复协议：服务端判据被简化成"中流双路 IDR = 新序列"，不需要额外握手状态机。**jetlink 没有视频编码所以不需要**——但如果 jetlink 引入硬编，这是必须同时搬的设计。

### 2.4 C4 侧分段计时环（frame_stages.h）

六段首尾相接，按 frame_idx 落 64 槽环形缓冲，随 REPLY 上报：

> `frame_stages.h:3-6`：取帧(eof→VisionIPC收到) → warp → 配对等待 → 硬编 → 发送 → 等 REPLY

**jetlink 缺这一块**：它有服务端遥测（`protocol.py:115-118`：srv_recv_us/prep_us/htp_us/total_us）和往返日志，但 C4 侧的"取帧→warp→发送"分段没有 uplif 到 UI/日志。诊断弱链路时这是必需的。

### 2.5 mDNS 服务发现（限子网）

> `server_locator.h:4-9`：只在 C4 当前 Wi-Fi 子网内发现——接口必须是 wlan0，解析出的 IP 必须落在 wlan0 的 IPv4 子网内；其他接口、别的局域网、avahi 陈旧缓存记录都不收

配合**手动 IP 兜底**（`Params "BigmodelServerHost"`）与**连败 3 次重新发现**（覆盖手机 IP 变化），健壮性明显优于裸拨网关。`mdns.py:1-10` 用 `avahi-publish-service` 发布，`PR_SET_PDEATHSIG` 保证随父进程退出。

**jetlink 的 Wi-Fi 模式**目前只拨默认网关（`wifi.py:12-14`）+ `/data/.jetlink_wifi_peer` 缓存（TTL 300 s）。`wifi.py:54-64` 已有 `local_addr()` 拿子网信息，只差 mDNS 接入。

### 2.6 「精简」方法论与注释纪律（工程治理）

git log 显示 lean-mici 有大量**主动删除**提交，值得 sp 参考：

```
9ca9552bf 删除 eagled 感知层（YOLO 检测/测距/标定/雷达关联）及其构建、发版、进程表、参数
45c22c6dc 删除 NNLC（神经网络横向控制）及其设置项
8ae263c2f lanlinkd: remove legacy avoidance monitor (avoidanced, radard, maneuver_status...)
794591d26 cereal: 删除 eagleDebug/eagleState 与 modelDataV2SP 变道拦截...；重生成 gen/cpp
896899f25 bigmodeld: 删空转的 FrameScheduler::on_frame_sent 与未用的 PairMatcher::reset
```

注释纪律也值得学：**README 头注即权威实现口径**（`bigmodeld/README.md:1-2` 声称"本注释即权威；原 spec 已归档 git 历史"），代码注释逐条带票号（"16 号"、"18 号 #4+#5 根因修复"），把设计决策的来龙去脉钉在代码旁。

### 2.7 AI 政策（docs/AI_POLICY.md）

```
要求：理解你提交的每一行；车控修复必须附 dongle ID + 日志 + 段；
禁止在 issue/PR 中放 AI 生成媒体；使用 AI 须在 commit 加 Assisted-by: 行。
```

这条与 jetlink 无关，但对 **sp 的贡献者流程**有直接参考价值（尤其是"车控修复需要真实证据"这一条，与 sp 的实车验证门槛同构）。

---

## 三、lean-mici 的弱点 / jetlink 的领先处

| 项 | lean-mici | jetlink |
|---|---|---|
| **保真度** | HEVC **有损**，大模型输入带压缩伪影；无公开 parity 数据 | **bit-for-bit**，parity gate 0.99957（`mac-performance.md:16`） |
| **平台广度** | Android App 强依赖（NsdManager/QNN），不覆盖 iPhone/Mac/PC | Jetson / Mac / Linux PC / iPhone / iPad / Android（`docs/backends.md`） |
| **模型生命周期** | 不在本仓库（App 侧自管） | 完整：HELLO→ENGINE_REQ→UPLOAD_CHUNK→PROGRESS(ETA)→ready（`protocol.py:63-84`） |
| **可移植性** | bigmodeld 是 `NativeProcess` 直挂 openpilot 树，强耦合 venus/V4L/VisionIPC | **适配器契约**：`interface.py` + `hooks.py`，jetlink **不 import openpilot**，可独立升级（`openpilot/__init__.py:7-28`） |
| **传输抽象** | 只有 TCP | vendor bulk / CDC-NCM TCP / **UDP 分片**（phone 线缆，绕开 TCP HOL，7.35→4.3 ms/帧，`link-protocol.md:33-42`） |
| **延迟** | 未给端到端 p50/p99 | Jetson 766 MB 模型 **24.5 / 25.8 ms**（p50/p99，`jetson-performance.md:12`） |
| **弱链路恢复** | TCP（有 HOL blocking 风险） | UDP 分片 + 帧级丢弃语义（缺片即当迟到处理） |
| **开关粒度** | 单一 `BigmodelToggle`（仅 offroad，`bigmodel.py:24-26`） | 三档链路模式（USB / iOS / Wi-Fi）+ 充电策略（`transport.md:29-37`） |

---

## 四、jetlink 借鉴清单（按价值排序）

### ⭐ P0：引入 C4 侧硬件编码作为「弱链路传输路径」

**做什么**：沿用 `system/loggerd/encoder/v4l_encoder.h` 的 `output_callback` 接缝（jetlink 已有能力，见 `bigmodeld/README.md:68-72` 的同款做法），在 jetlink 里加一条"HEVC 压缩帧"传输模式，用于 Wi-Fi / 蜂窝 / 远距离场景。

**收益**：
1. 单帧 393,304 B → ~8 KB，**48× 带宽缩减**，让 Wi-Fi 真正可用（当前 Wi-Fi lossless 只 2.1×）
2. **CPU 零成本**（venus 硬编），从而解掉 `joining.py:33-38` 那个"9 ms/帧 → 饿死 DM 模型"的约束 → **可以 20 Hz 常发** → 接管零冷启动
3. 复用 lean-mici 已验证的参数：HEVC Main / VBR / 无 B 帧 / GOP 20 / 2 Mb/s/路

**必须同时搬的三样**（否则会踩坑）：
- **序列头门**（`uplink_sender.h:14-19`）：断档后首帧必须是双路 IDR 对，服务端才能用"中流双 IDR = 新序列"判据
- **配对前 warp + 10 ms 容差配对**（`README.md:29-33`）：双路不因单路缺帧撕裂
- **MetaCache 查不到不弹队**（`README.md:87-91`）：旧实现弹空全队会把新序列的双路 IDR 吃掉

**风险与取舍**：HEVC 有损 → 输出不再 bit-for-bit，**parity gate 0.99957 会失效**。建议做成**双模式**：USB 3 上继续原始帧保 parity；弱链路才用 HEVC。并且需要实测压缩伪影对大模型输出的影响（用 route 回放做 A/B）。

### ⭐ P1：C4 侧六段分段计时（`frame_stages.h` 直接可搬）

64 槽环形缓冲 + 按 frame_idx 索引 + 随 REPLY 上报 `BigStageTimes`。jetlink 现在只有服务端遥测，缺 C4 侧分段。诊断弱链路（是 warp 慢、还是发送慢、还是等回复慢）必需。着落点：`jetlink/openpilot/link.py` + `status.py`，capnp 侧加 `BigStageTimes` 等价结构。

### ⭐ P1：mDNS 服务发现（限 wlan0 子网）+ 手动 IP 兜底

`server_locator.h:4-9` 的判定逻辑（接口必须是 wlan0 + IP 必须落在 wlan0 子网 + 连败 3 次重新发现）可直接移植到 `jetlink/comma/wifi.py`。当前 Wi-Fi 模式只拨网关，在"手机是 peer 客户端而非网关"的 AP 场景下会失败（`wifi.py:54-64` 的 `local_addr()` 注释已承认这点，但没做发现）。

### P2：切换期全头交叉淡入（SourceBlender）

jetlink 现在是硬切（历史重置 + 1 s 证明期）。两个模型的规划路径差 ~195 m（`joining.py:44-46`），硬切会突兀。`big_model.py:76-103` 的 10 帧（0.5 s）线性淡入 + 兜底帧 hold 最近大模型输出，过渡更平滑。

**注意**：**不要因此放弃 jetlink 的 `in_control` 门**（`joining.py:44-47`：never swap while the plan is steering）。淡入是体验优化，`in_control` 是安全设计，两者应结合——"只在未控车时切换 + 切换过程淡入"。

### P2：REPLY 迟到判定的 `_gave_up_t_eof` 归零法

> `big_model.py:143-145`：`if t_eof <= self._gave_up_t_eof: 判迟到`

一行判定替代计数窗口，干净。jetlink 用"连续 5 次 / 10 s 内 20 次"的双窗口（`link-protocol.md:24-29`），两者可叠加：**硬截止判据用 jetlink 的（更严），遥测迟到统计用 lean-mici 的归零法（更简）**。

### P3：工程治理

- **主动删死代码的节奏**（lean-mici 每做完一个特性就反手清残余）——sp 的 `carrot/` 移植后也有清理空间
- **注释即权威 + 票号溯源**——sp 已部分做到（`memory/` + `docs/`），可更彻底地钉在代码旁

---

## 五、反向：lean-mici 该学 jetlink 的

（供完整判断，不影响 sp 的决策）

1. **平台广度**：jetlink 的 Swift 统一服务端一次覆盖 5 类算力端，lean-mici 锁死 Android + QNN
2. **模型生命周期管理**：jetlink 有完整的下载/上传/构建/准备/ETA 流程，lean-mici 侧完全缺失
3. **适配器契约**：jetlink 不 import openpilot，`interface.py` + `hooks.py` 通过 API 版本绑定，可独立发版；lean-mici 的 bigmodeld 是深耦合 `NativeProcess`
4. **USB 3 有线路径**：2.1 ms 传输（`jetson-performance.md:41-42`）vs Wi-Fi 36.4 ms，在有线可用时是巨大优势
5. **UDP 分片**：绕开 TCP 的 per-segment 开销（272 段 → 7 个包），弱链路必备
6. **PADDED / USB 2 回退语义**（`protocol.py:31-42`）：16 KB 对齐避免短包歧义 + dwc3 TX FIFO 越过问题的工程细节

---

## 六、一句话总结

**lean-mici 与 jetlink 是同一问题的两种解**：lean-mici 用"C4 硬编压缩 + 手机 NPU + Wi-Fi"换零外设与低门槛，代价是有损与平台窄；jetlink 用"USB 3 原始帧 + 多平台服务端"换保真与广度，代价是硬件门槛与切换冷启动。

**jetlink 目前最值得偷的一招是 C4 侧 venus 硬编**——它同时解决"Wi-Fi 带宽"和"常发帧的 CPU 成本"两个卡点，且能让 jetlink 从"接管才发 + 冷启动"变成"常发 + 接管即热"。这一招的价值远超其余四条之和。

**建议动作**：先在 `E:\sp` 用 route 回放做一次 A/B——同一段 route，分别用原始帧和 HEVC 2 Mb/s 帧跑大模型，量化压缩伪影对输出的影响。如果影响在可接受范围，再考虑实现双模式传输。
