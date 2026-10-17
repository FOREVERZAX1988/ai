# JetLink —— 行车预览为什么好很多，以及它每 5–30 s 塌一次的真正原因（2026-10-17 上午）

> 设备 `comma-a821bfb2`（tizi，Porsche Macan）｜jetlink `cn` `814cf63` → 第一轮 +1 提交 `e20dc25` → **第二轮 +2 提交 `e021dd3`**（均已推 fork，未推上游）
> 上一轮：`ai/docs/JETLINK_WIFI_PIPELINE_1017.md`（B/D/C 落地）、`JETLINK_WIFI_FPS_1016.md`（帧预算）
> 手机：一加16（PYB110 / SM8975 / Android 17），app `io.zoompilot.jetlink.android` 0.8.7（807）
> 链路：**Wi-Fi**，手机做热点 `wlan2 10.248.21.223/24`，comma `wlan0 10.248.21.60/24`（USB 线只供 adb）

## 0. 结论先说

| 问题 | 答案 |
| --- | --- |
| 「比昨天好很多」是优化还是网络？ | **两者都有，而且能分开量**。优化：`wait` 从 50.5 ms → **0.0 ms**，`pipelined` 448/492、`held` 0，手机的 `queue` 从 0.4（空转）→ 3.5 ms（在算），`0 lost, net drops 0`。网络：同一条链路 ping 0.2 s 间隔 **6.1 ms**（昨晚 26.8–45 ms）。C 流水线是「不再等自己的回包」，与网络无关 |
| 「还有什么需要优化」 | **有，而且是这轮的主要发现**：预览每 5–30 s 整条链路被放弃一次。今天 34 次 demote：**21 次**撞 client 的 0.2 s deadline，**12 次**是 TCP 写超时，1 次 gadget 掉 |
| 这 21 次修了吗 | **修了并已推**：`e20dc25`。预览的链路现在「patient」：欠着的帧**扣住**（不发、照旧发上一份答复），不再把链路判死；交还画面的仍是 `PREVIEW_SILENCE` 5 s |
| 那 12 次呢 | 第一轮**没修**（见 §4）；**第二轮已修并推送**：传输层保「续写」，写不进去就扣帧而不是弃链（`18848c2`，见 §6） |
| APK 装对了吗 | **装对了**。`0.8.7-1017-2` 的 target commit = **`814cf63`**（= D 那三个提交之后的 cn 头），app 里低延迟 Wi-Fi 锁在跑。本轮修复**是 comma 侧 Python，不用再装包**，`/data/openpilot/jetlink` 就是 `jetlink_repo/jetlink` 的软链，改完即生效 |
| 「USB 线插上了」 | adb 走 USB（`3B16A50049700000`），但 **jetlink 链路没走**：`JetlinkLink=3` = `MODES=('off','usb','ios','wifi')` 里的 **wifi**。要跑线缆得把 Jetlink 设置改成 `usb`（1） |

## 1. 现场数字（今天 Wi-Fi 预览，492 条帧日志）

| 量 | 昨晚（21:29–21:46） | 今天 |
| --- | --- | --- |
| warp / data / send | 2.5 / 0.6 / 1.8 ms | 2.4 / 0.7 / **4.2** ms |
| **wait** | **50.5 ms**（阻塞帧线程） | **0.0 ms**（pipelined） |
| server gpu / **queue** / total | 25.1 / **0.4** / 25.7 ms | 25.1 / **3.5** / 27.7 ms |
| held : pipelined | 396 : 0 | **0 : 448** |
| ping 到手机（0.2 s 间隔） | avg 26.8–45 ms | **avg 6.1 ms** |
| 结果 | 17 分钟 637 帧后 `drop 1, lag 13` | 24 分钟 **34 次**「joined → 塌 → 60 s backoff」 |

⇒ 帧本身的账已经健康了（自有开销 ~7 ms，相机 50 ms，余量很大），**塌的不是帧，是链路被判死**。

## 2. 根因：0.2 s 的 deadline 是按「一帧」定的，流水线让它按「一队」用

`link.py` 把客户端的 deadline 设成 `INFERENCE_TIMEOUT = 0.2`（注释：四个帧周期，也 fit 进 modelV2 的 0.5 s alive 限制）。`client.infer_begin` 用它判「对面是死了还是慢」：

```python
if self.waiting_for() > self.deadline:   # 最老的那帧还没答多久了
    self.dead = True                      # ← 判死，整条链路作废
```

`waiting_for()` 量的是**最老的在飞帧**。以前一帧一帧等（`hold` 46/55 ms），在飞永远 ≤ 1–2，一次 200 ms 的静默 = 一帧等的 200 ms，判死是合理的。C 的流水线**不再等**，于是队伍按相机节奏累积：一次 200 ms 停顿（一次 TCP 重传的 RTO 就是 200 ms）留在飞 4 帧 → 正好撞上 0.2 s → 判死。今天的 21 次全是这个名字：

```
LinkError: no answer to 4 frames in 0.2s; link abandoned      # 12 次
LinkError: no answer to 3 frames in 0.2s; link abandoned      # 12 次
LinkError: no answer to 5 frames in 0.2s; link abandoned      #  5 次
```

上一轮文档 §6 写「最终由 client 的 3 s deadline 触发一次 demote+retry」——**那个 3 s 是 `FRAME_TIMEOUT`，而这条路设的是 0.2 s**。设计意图（宽）与实现（0.2）不一致，是这次的核心。

## 3. 改动（`e20dc25`）：预览是 patient，欠着的帧扣住，不判死

| 位置 | 改动 |
| --- | --- |
| `client.patient`（新） | 与 `tolerate_failed` 同一个来源、同一个理由：预览永远不接管，所以「落后」不等于「没了」 |
| `client.infer_begin` | `self.patient and skip_if_busy` 时**不发**、`return None`：这一帧走「链路吃不下的帧」那条既有路径，循环照旧 publish 最新答复；判死那条留给 `skip_if_busy=False`（会话第一帧，没东西可 publish）与滚轮 |
| `model_state.preview` setter | `self.client.patient = self._preview`（与 `tolerate_failed` 并列） |
| 交给谁交还 | 不变，仍是 `PREVIEW_SILENCE` 5 s —— 这正是代码里早就写着的那句「a preview is held to PREVIEW_SILENCE and to nothing else」 |

**没动**：滚轮路径（不设 patient，读法一字不改）、`INFERENCE_TIMEOUT`、`PREVIEW_SILENCE`、丢帧规则（`joining.py` 里预览本来就已豁免 `DROP_LIMIT`）。

测试：`tests/test_client.py` +2（patient 扣住 / 不可省的一帧仍判死，datagram 子类各多一份）、`tests/openpilot/test_model_state.py` +1（wiring）。相关三套 **117 passed**，4 个 ERROR 与改动前**逐条相同**（`tests/openpilot/conftest.py` 的「别碰机器自己的文件」守卫，环境问题）。

## 4. 还没修的：send 路径（今天的 12/34）

```
File ".../transport/tcp.py", line 156, in _write
raise LinkError("send failed: timed out")
  ← client.infer_begin → transport/base.py:87 try_send → send(...) → tcp._write
```

`try_send` 的契约本来是「链路要让你先等对面把之前的消息收掉，就返回 False，让调用方扣住」——**只有会排队的传输做得到（FfsTransport 的 QUEUED_LIMIT）**；`StreamTransport.try_send` 直接 `send()`，于是线上拥塞时它**阻塞、然后超时、然后杀掉整条链路**，而调用方早就说过这一帧可以不要。

`send 4.2 ms` 的中位说明线上通常很空（200 ms 是它 50 倍），一旦超时就是**消息写了一半**：流里半条消息收不回来，对面会把下一条的头当成上一条的身子 → 只能弃链。所以不能像 §3 那样「扣住就好」，必须**避免开始写**或**允许续写**：

1. **传输层可续写 TX**（推荐）：`try_send` 只把消息放进传输层自己的队列立刻返回，由写者续。「写一半」变成传输层的状态，帧线程永不阻塞 —— 与 `RxBuffer`「部分读保留、漏一个 deadline 只丢一帧」对称。
2. **把 datagram 通道从线缆放到 Wi-Fi**：`infer_begin` 里「可丢的帧走 datagram」这条路已经是为这件事设计的（`_take_reply` 会把丢掉的帧从在飞里摘掉），现在只在手机线缆上启用（`TcpTransport.use_datagrams` 的 offer 只在 cable 被接受）。要在 Wi-Fi 用，得让手机侧 hello 在 Wi-Fi 上也 offer 一个 UDP 口。
3. （本轮**不做**）用 `SIOCOUTQ + SO_SNDBUF` 预判「这次写会不会阻塞」：本机实测 SO_SNDBUF 生效 8 MB（请求 4 MB 被内核翻倍），而对端窗口关掉时会话实际的阻塞点在 ~5.5 MB（skb 开销），**检查不可靠**，猜错就是「该扣不扣（仍然 desync）」或「不该扣乱扣（画面变卡）」。

## 5. 复验清单（真车 / 车上，一次 Wi-Fi 预览就够）

1. 让 manager 重拉 modeld（`IsOnroadPreview` 关→开，或重启 modeld）——**必须**，否则跑的还是旧的 import；
2. `grep 'jetlink: frame' swaglog` ⇒ `wait` 仍应 ≈ 0.0 ms、`pipelined` 照旧；
3. 出现 200 ms 级停顿时：应看到帧被**扣住**（`held …, not sent`）而**没有** `large model failed mid-drive`，
   日志里**不应再出现** `no answer to N frames in 0.2s`；
4. `join` 摘要里 `failure` 计数应显著下降（今天是 24 分钟 34 次）；
5. 仍可能看到 `send failed: timed out`（§4）——那是另一件事，看到它请按 §4 的 1/2 推进。

---

## 6. 第二轮：写路径落地（`18848c2` + `e021dd3`，已推 fork）

> 触发：§5 的复验做完了（用户把行车预览关→开，modeld 08:00:43 重拉），现场把「还剩的那 12 次」钉成了 **40 次写失败**，全部同一种死法。

### 6.1 复验：patient 那一轮是对的

| 量（日志实测） | 08:00:43 之前（05:50–08:00，2 h 10 m） | 关开之后（08:00:46–08:03:12，2.5 min） |
| --- | --- | --- |
| 帧日志 / 其中 pipelined | 1183 / 1062 | 100 / 95 |
| `send failed` | **40** | **0** |
| `large model failed mid-drive` | **40** | **0** |
| `no answer to N frames in 0.2s` | 0（本轮前已由 `e20dc25` 消掉） | 0 |
| `held …, not sent` | 40（= 每次弃链一次） | 6（累计 17→101，**没有任何 demote**） |
| `wait` 中位 / `send` 中位（max） | 0.0 / 4.2（**178.4**）ms | 0.0 / 3.8（**5.3**）ms |
| server `gpu` 中位 | 23.9 ms | 22.8 ms |
| 结果 | 每 ~3 分钟弃链一次 | 大模型在线 100%，`drop/lag` 不再出现 |

⇒ 「帧被扣住」这条路已经按设计在跑（`held (101 so far, not sent)` 而链路不动），而且**剩下的失败 100% 集中在写路径**：40 次里的每一次都是 `send failed: timed out (tcp)`，与 §4 的判断完全一致。

### 6.2 改动：`StreamTransport.try_send` 不再等于 `send`

契约（`Transport.try_send`）本来就说「链路会让你先等对面把之前的消息收掉 → 返回 False，让调用方扣住」，但 `StreamTransport.try_send` 直接 `send()`，线上拥塞时**阻塞 → 超时 → 弃链**，而调用方早就说过这帧可以不要。

落地的不是「预判」（§4 里实测不可靠的那条），而是**续写**：

| 位置 | 改动 |
| --- | --- |
| `transport/base.py` `StreamTransport.try_send`（新） | 先交还上一帧欠下的尾巴；**尾巴没交完就返回 False**（这帧一个字节不发）；否则非阻塞写这一帧，写进去多少算多少，**没写完的部分复制到 `_tx` 由下一次 send 续**。任何情况都不等 `timeout`（和 gadget 的 `QUEUED_LIMIT` 同一个口径） |
| `transport/base.py` `_flush_tx`（新） | 非阻塞地把 `_tx` 交给内核；内核自己会把它发完（SO_SNDBUF），所以「交不动」就是对面窗口关着，不是本端没干活 |
| `transport/base.py` `send()` | 发自己的消息**之前**先把 `_tx` 交掉：对面读的是一条流，半条消息不是它能跳过的 |
| `transport/tcp.py` `_write_briefly`（新） | 不等版的 `_write`：socket 置 timeout 0 再 `sendmsg`，内核拿不下就是 0；真错误（EPIPE/ECONNRESET）仍抛 `LinkError` |
| `model_state.py` 发送失败日志 | 打**真正的异常**（TCP 没有 `last_send`，原来那行只打出一个空 `{}`，40 次的死因就是这么丢的） |

为什么安全：**「没发出去」是唯一可以重新决定的情况**，而 TCP 只有「内核一个字节都没收」才会返回 0（收下了就返回计数），所以 False 一定意味着对面没有这帧的任何字节，流还是干净的、可以下一帧再来；反过来，只要有字节出去了，这帧就算被对面收下了，剩下的由 `_tx` 按序补完 —— 这正是 §4 说的「撤销不了」。

### 6.3 测试（`tests/test_stream_hold.py` 新增，6 条；`tests/test_protocol.py` 的 `_TimedTransport` 跟契约一起改）

1. 半条消息出去了 ⇒ 返回 True，且对面**只**读到这一条的前缀（不是整条，也没有下一条的任何字节）；
2. 对面一点空间都没有 ⇒ 返回 False，**一个字节都不上线路**；
3. 帧循环连跑：对面读到的字节流**永远等于**「已提交的那些帧」的前缀 —— 不重、不乱、被扣下的帧不出现；
4. `send()` 会先把欠下的尾巴交完再发自己的消息（字节级对齐）；
5. 预览级：对面停止读取 ⇒ 帧被扣住、`client.dead` 仍为 False；对面恢复读取 ⇒ 帧重新放得进去；
6. 全量：`1095 passed, 2 failed, 4 errors` —— 这 2 failed（`test_comma_wifi`，本机真在 Wi-Fi 上）与 4 errors（`test_imports`/`test_api` 的机器守卫）在**改动前后逐条相同**；ruff 干净。

### 6.4 生效与复验

**本轮改的是 comma 侧 Python，不需要装任何 APK**；但 modeld 要重新 import：**行车预览关→开一次**（`/data/openpilot/jetlink` 是 `jetlink_repo/jetlink` 的软链，commit 已在树里）。

复验看三件事：

1. 出现 200 ms 级停顿时：日志应只有 `held …, not sent` 与 `wait 0.0 ms, pipelined`，**不应再有** `send failed: timed out (tcp)`，也不应有 `large model failed mid-drive`；
2. `join` 摘要里的 `failure` 计数应显著下降（本轮前是 2 h 10 m 40 次）；
3. 万一还出现 `send failed`：现在那行会带**真异常**（不再是 `{}`），按它区分「发送超时 / ECONNRESET / 对面关连接」，再决定要不要走 §4 的第 2 条（把可丢帧的 datagram 通道也搬到 Wi-Fi，需要手机侧 hello 在 Wi-Fi 上 offer UDP 口）。

### 6.5 仍然不做 / 不在这一轮

- **B（响应量化/压缩）**：不做，前提是错的（响应 8,292 B，见上一轮文档）；
- **手机侧（Swift `JetlinkServer`）的写路径**：它有 `SO_SNDTIMEO`（`Transport.swift`），但那是 8 KB 答复且 comma 自己在排空收缓冲，目前不是瓶颈，本轮不动；
- **SO_SNDBUF 的 8 MB**：它决定「一条链路最多压多少在飞」（393 KB × ~20 帧）。收小能减少陈旧帧，但会更容易扣帧，属于**路面调优**，不在补丁里。
