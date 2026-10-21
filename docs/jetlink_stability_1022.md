# JetLink over Wi-Fi：「行车预览 + 手机在线」稳定性实测报表（2026-10-22 07:18–07:24）

> 设备 `comma-a821bfb2`（tizi，Porsche Macan）｜分支 `sync/upstream-1019` @ `918150e5ec`（round 20 合并后）
> 链路 **Wi-Fi**（`JetlinkLink=3`），手机 jetlink 端 `192.168.10.65`（MAC `de:1c:2c:79:86:91`，Android 随机 MAC）
> 第二台同网设备 `192.168.10.201`（MAC `a8:a1:59:db:bb:97`）挂在 op 助手 `:5090` 上
> 现场条件：驾驶者已开 **行车预览**（`IsOnroadPreview`）+ 手机 jetlink 在线，车停着（offroad，`vEgo=0`）
> 复现命令：`python3 ai/scripts/jetlink_stability_capture.py --duration 60`（新脚本，本轮新增）

## 0. 结论先说

| 问题 | 答案 |
| --- | --- |
| 帧路径（jetlink 大模型这条）稳不稳 | **稳**。60 s 窗口：**20.00 fps**、帧间隔 p50 **50.012 ms** / 最大 50.136 ms、标准差 **0.038 ms**；应用层 `send` 4.04 ms、手机侧 queue 4.35 ms、`total` **25.4 ms**（p95 28.97 / max 30.2）；`stalls 0`、`hiccups 0`、`link abandoned 0`、`demote 0` |
| 和合并前的记录比有没有退化 | **没有，略好**。1017 那份现场记录是 warp 2.4 / send 4.2 / gpu 25.1 / queue 3.5 / total 27.7 ms；现在 warp 2.76 / send 4.04 / gpu ~21 / queue 4.35 / total **25.4 ms**。`held` 比例 1017 是 0:448，现在是 **68:8332（0.81%）** |
| 那驾驶者「完全稳不住了」是什么 | **不是帧路径，是空口和 TCP 缓冲**。同一时刻 wlan0 实测 **rx 16.6 Mbps + tx 28.2 Mbps ≈ 45 Mbps**；其中 jetlink 占 tx 26.6 Mbps，另有**一条与 jetlink 无关的入向大流**——`192.168.10.201 → :5090` **14.7 Mbps**，并且它的发送队列压过 **2.5 MB**、偶发 **180 KB** |
| 合并有没有把优化弄没 | 从数字上看没有（见上两行 + §3 的 18 个 session 全表）。**但**这轮确实量到两个新东西：①第二条入向大流和它造成的 MB 级 send-Q 积压 ②停车状态下 `xiaoge_data` 常驻 **24% CPU**、整机 **65%**、温度恒定 **75 °C** |

## 1. 量了什么、怎么量

新脚本 `ai/scripts/jetlink_stability_capture.py`，两个独立来源交叉：

* **内核侧**（1 Hz，`ss -tni`）：`:5090` 各连接的 **Send-Q**、`rtt`/`rttvar`（内核自己的抖动估计）、`retrans`、`bytes_acked` 速率、连接出现/消失时间。
* **应用侧**（swaglog，modeld 写的）：每帧 `jetlink: frame N ... warp/send ... server gpu/queue/total`、1 Hz 的 `stages frame N` 心跳（**帧间隔方差就是由它算的**）、以及每 30 s 一条的 `trips frames N ... held H pipelined P span_s S p50/p99/max`（`held` = 扣住没发的帧 = 链路真实损失）。
* 另采 `/proc/stat` + `/proc/<pid>/stat`（整机与各进程 CPU，1 Hz）、`/sys/class/thermal/*`（温度）、`/proc/net/dev`（空口总吞吐）。

产物：`artifacts/jetlink_stability_20261022-071851.json`（60 s）、`artifacts/jetlink_stability_20261022-072202.json`（45 s，带每连接 send-Q 时间线）。

## 2. 三个数：Send-Q / rtt 抖动 / 帧间隔方差

### 2.1 帧间隔方差（应用层，60 s / 1200 帧）

| 量 | 值 |
| --- | --- |
| 帧率 | **20.00 fps**（阶段心跳推算 19.997，sd 0.015） |
| 帧间隔 | p50 **50.012 ms**，p95 50.048 ms，max 50.136 ms，**sd 0.038 ms** |
| 1 Hz 心跳间隔 | p50 1000.9 ms，p95 1050.5 ms（心跳本身按 10 帧一批，抖动来自发布节拍，不是丢帧） |
| 卡顿（>1.5× 心跳周期） | **0 次** |
| 单帧 hiccup（send>10 ms 或 server total>45 ms） | **0 次** |

### 2.2 内核 Send-Q（`:5090` 上全部连接求和，1 Hz × 53 次）

| 量 | 值 |
| --- | --- |
| 为 0 的采样 | **49 / 53** |
| 非零 | 4 次，**max 145,328 B**（≈145 KB 一次积压） |
| 45 s 那轮（带每连接时间线） | 单点 **179,921 B @ t=3.5 s**，落在 `192.168.10.201:1157` |
| 5 s 抽样撞到的最坏值 | `192.168.10.201:3808` **2,608,013 B（2.5 MB）** 未发出——对端不读，内核替它缓存了几秒 |

> 这条 2.5 MB 是**本轮最该记住的数字**：一个不读的客户端能让我们的 socket 里堆几 MB，这些字节会持续抢空口和重传，而 jetlink 的帧线程完全看不见它。

### 2.3 rtt / rttvar（按连接，不用「最忙的那条」混算，避免把两条连接的差当成抖动）

| 连接 | 角色 | rtt 均值 / max | rtt 逐秒跳变（mean / max） | rttvar 均值 / max |
| --- | --- | --- | --- | --- |
| `:1156` | 批量、本轮 4.37 MB | 6.84 / 18.9 ms | **4.85 / 12.2 ms** | 6.08 / 24.6 ms |
| `:2075` | 批量、本轮 2.18 MB | 3.64 / 14.7 ms | 0.49 / 9.3 ms | 1.22 / 20.9 ms |
| `:1157` | 空闲，**rttvar 卡在 11.9 ms 不动** | 8.31 / 8.42 ms | 0.11 / 5.8 ms | 11.66（无变化） |
| `:4754` | 控制/心跳 | ~50 ms | — | — |
| modeld → `.65:5599` | **jetlink 本体** | — | — | — |

（`:4754` 的 50 ms 是那条小连接自己的 RTT 估计，`minrtt 44.2`，不是空口变差；批次连接同刻 minrtt 只有 1.0 ms。）

## 3. 空口账：谁在吃 Wi-Fi

10 s 同时抽样（07:24:0x，`/proc/net/dev` 与 `ss -tani` 对齐）：

| 连接 | 方向 | 速率 | retrans | send_q |
| --- | --- | --- | --- | --- |
| `modeld 192.168.10.79:39098 → 192.168.10.65:5599` | **jetlink 上行** | **tx 26.6 Mbps** / rx 1.3 Mbps | +0（累计 0/215） | 0（早前撞到 165,172 B） |
| `ai.aid :5090 → 192.168.10.201:3808` | **非 jetlink**（op 助手） | tx 1.0 Mbps / **rx 14.7 Mbps** | +0 | 0（早前 2.6 MB） |
| **wlan0 合计** | | **rx 16.6 Mbps + tx 28.2 Mbps** | | |

⇒ 空口上跑着 **≈45 Mbps**，其中 jetlink 26.6 Mbps、另一台设备的入向 14.7 Mbps。jetlink 一条链路就要 26 Mbps（≈166 KB/帧 @20 fps），再加一条 15 Mbps 的入向流，手机热点这条路上就是「谁都在等」——这是「稳不住」的量级来源，不是帧路径退化。

## 4. 现场回溯：本机今天 18 个 session（07:03–07:19，每 30 s 一条）

| 时间 | span_s | frames | held | pipelined | p50 | p99 | **max** | server |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 07:03:27 | 30.0 | 599 | 0 | 99.8% | 7.8 | 11.7 | **104.4** | 23.6 |
| 07:03:57 | 60.0 | 1199 | 0 | 99.9% | 7.6 | 11.3 | **104.4** | 23.6 |
| 07:04:27 | 90.1 | 1800 | 1 | 99.9% | 7.4 | 8.4 | 10.2 | 24.2 |
| 07:04:57 | 120.1 | 2401 | 1 | 99.9% | 7.4 | 8.3 | 9.8 | 24.8 |
| 07:05:27 | 150.1 | 3001 | 1 | 99.9% | 7.5 | 8.2 | 8.5 | 24.6 |
| 07:06:16 | 30.0 | 600 | 0 | 99.8% | 7.4 | 8.4 | **87.7** | 25.6 |
| 07:06:46 | 60.0 | 1201 | 0 | 99.9% | 7.4 | 8.2 | 14.7 | 25.5 |
| 07:07:16 | 90.1 | 1802 | 0 | 99.9% | 7.4 | 8.1 | 14.7 | 25.5 |
| 07:07:46 | 120.1 | 2402 | 0 | 100% | 7.4 | 8.2 | 14.2 | 25.4 |
| —（07:07:46 → 07:15:55 **8 分钟无帧**，modeld 07:12 重启） | | | | | | | | |
| 07:15:55 | 30.0 | 601 | 0 | 99.8% | 7.7 | 11.5 | **107.7** | 24.9 |
| 07:16:25 | 60.1 | 1201 | 20 | 98.3% | 7.7 | 11.1 | 12.2 | 24.8 |
| 07:16:55 | 90.1 | 1801 | 20 | 98.8% | 7.5 | 8.6 | 10.5 | 25.0 |
| 07:17:25 | 120.1 | 2401 | 27 | 98.8% | 7.4 | 8.2 | 8.9 | 25.4 |
| 07:17:55 | 150.1 | 3001 | 50 | 98.3% | 7.5 | 8.3 | 9.5 | 25.5 |
| 07:18:25 | 180.1 | 3601 | 50 | 98.6% | 7.4 | 8.3 | 9.5 | 25.0 |
| 07:18:55 | 210.1 | 4201 | 50 | 98.8% | 7.4 | 8.1 | 9.2 | 24.7 |
| 07:19:25 | 240.1 | 4801 | 50 | 98.9% | 7.4 | 8.3 | 9.2 | 25.1 |
| 07:19:55 | 270.1 | 5401 | 53 | 99.0% | 7.5 | 8.5 | 9.2 | 25.2 |

读法：每个 session 的 `frames/span_s` 都是 **20.0**（没掉过帧率）；`held` 只在 07:16 那一批里新增了 53 个（占 0.98%）；三条 `max` 尖峰（104/88/108 ms）都出现在**链路刚开始的 30 s 内**，之后 p99 一直在 8.x ms。也就是说：链路建立后是稳的，抖动被集中在建链/换模型的瞬间。

## 5. 设备侧：CPU 和温度（同一窗口）

| 量 | 值 |
| --- | --- |
| 整机 CPU（8 核口径的 busy%） | mean **65.4%**，p95 70.4%，max 71.4% |
| `xiaoge_data` | **24.2%**（停车状态下常驻，见 §6） |
| `modeld`（jetlink 帧线程本体） | 4.5% |
| `carrot_man` / `webuid` / `jetlink_adapter` | 2.35% / 1.72% / 0.09% |
| 最高温 | **75.0 °C（60 s 内 53 个采样一模一样，sd=0）** |

## 6. 结论与下一步（按性价比排）

1. **先摘掉那条非 jetlink 的入向大流**：`.201` 往 op 助手 `:5090` 灌 14.7 Mbps 并让我们堆过 2.5 MB send-Q。先确认 `.201` 是哪台设备（本轮没在 aid 日志里留 IP，只有 MAC `a8:a1:59:db:bb:97`）；如果是手机上后台开着的面板/预览页，关掉它再看一轮，这轮数字可直接对比（同一脚本、同一 label）。
2. **停车时停掉 xiaoge 推理**（原 A 项）：`xiaoge_data` 24% CPU 在停车时纯属白烧，占整机 65% 的三分之一强，而 modeld/UI 正好在抢同一批核。改的是 `xiaoge_data/v_asm_server` 的门 + 补单测，不碰控制链。
3. **给不读的客户端加背压上限**：`:5090` 上出现 MB 级 send-Q 说明服务端愿意替不读的对端缓存任意多字节。预览类流量应该是「只发最新」，积压超阈值就丢旧帧或断开该客户端——这是本轮新发现，属可做的小改动（单独一轮，不动 jetlink）。
4. 若第 1 步之后 **jetlink 单跑仍不稳**，再动链路参数（上行质量/帧预算），并以本报表为基线 A/B；判据：`interval_ms.sd`、`held/span`、`send_q_nonzero_seconds`、`stage_tick 卡顿次数` 四项同时看。

> 注意：本报表全程 **没有** 出现 `link abandoned` / `no answer to N frames` / `demote` / `net drops` / `lost` 任何一个关键字（事件扫描 0 命中）。1017 文档里那 34 次「joined → 塌 → 60 s backoff」的形态，这一轮 **一次都没复现**——所以「合并把优化弄没了」这个假设，用现场数字看是不成立的。

---

# 附：A 项与 `.36` 候选（同轮完成，2026-10-22 07:25–07:45）

## 7. 停车停推理（`xiaoge_data` / `v_asm_server`）

现场数字是这一项的依据：停车 + 行车预览时 `xiaoge_data` 常驻 **24.2% CPU**（整机 65.4%），而它唯一在干的活是车道模型按 `OnnxLaneIntervalMs`（默认 1000 ms，下限 600 ms）跑推理——每帧约 400 ms，正好≈半个核。

改动（父仓 `openpilot/sunnypilot/carrot/xiaoge/v_asm_server.py`，不碰控制链）：

| 改动 | 说明 |
| --- | --- |
| `PARKED_SPEED_MPS = 0.3` + `parked_gate(speed)` | 纯函数，`vEgo < 0.3 m/s`（≈1 km/h）判「停着」。阈值取 0.3 是因为真实蠕行也远大于它（0.3 m/s × 1 s = 30 cm） |
| `_update_inference_gate()` | 每帧读一次 `carState.vEgo`，把结论存进 `self.inference_gate`；两条相机线程（宽/窄）都先问它 |
| `run_road_camera`：`if not infer_active or not self.lane_inference.valid: continue` | 停车时**仍然收帧**（快照、`status()`、网页面板全部照常），只是不跑 ONNX |
| `nv12_y_plane(...)` 移到「确定要推理」之后 | 原来每帧都做一次 2.7 MB 的 Y 平面拷贝（20 帧/s ≈ 54 MB/s），而 1 Hz 才用一次 |
| `_lane_change_gate()` 抽出 + `parked` 优先 | 盲区门原来只报「speed outside 30-120 km/h」，现在停车单独报 `parked (inference off)`，面板上能看出是哪条闸关的 |
| `status()` 新增 `inferenceGate` | `{active, reason, speed}`，网页/手机都能看到停车门的状态 |

两个刻意的选择：

1. **carState 拿不到时 fail-open**（继续推理）。这个进程是 `carrot_enabled` 起的、offroad 也在跑；把「不知道」当成「停着」会在高速上 carState 抖动时静默丢掉车道数据——比多烧点 CPU 危险得多。
2. **门槛只在「停」这一侧**，不引入「点火/挂挡」这类需要新增订阅的信号，所以 `SubMaster` 订阅面没变；两条线程共用 `SubMaster` 本来就有竞态（`update()` 不是线程安全的），这次一并加了 `self.sm_lock`，两处 `sm.update(0)` 都在锁里。

单测：`openpilot/sunnypilot/carrot/tests/test_v_asm_parked_gate.py`（**19 passed**）——判据函数 6 例（0/0.29/0.30/15/负数/未知）、接线 4 例（停车/行驶/carState 死/字段读不出）、盲区门 4 例、`status()` 契约 2 例、以及**源码顺序断言**（先查门 → 再建 Y 平面 → 再推理）。

回归：`test_xiaoge_cereal_fields.py` + `test_xiaoge_proxy.py` + 新增 = **31 passed**；`carrot/tests` 全量 **788 passed / 6 skipped**（2 个 params 用例单独跑通过、全量跑失败，属既有设备侧顺序污染，与本次改动无关，见 §9）。

## 8. `.36` 候选（SM6450 Beam Pro）清掉

`.36` 的问题不是「连不上」，是**太容易被连上**：它的 `:5599` 永远 OPEN，而扫网段时 `discover()` 按地址序返回第一个应答的主机，`.36 < .65`，所以只要记住的 peer 过期/失效，就必然先撞它，然后 engine 构建必失败（QNN EP 不认 nhwc Conv 节点），每次驾驶白试一轮。

改动（`jetlink_repo/jetlink/comma/wifi.py`）：

* 新增 `BLOCK_FILE = /data/.jetlink_wifi_blocked`（一行一个地址，`#` 注释）+ `blocked_hosts()` / `block_host()`；`discover()` 的 `blocked` 集合变成 `skip | UNUSABLE | blocked_hosts()`，`_saved_peer()` 也一起查——否则「记住的 peer」这条捷径会绕过黑名单。
* 与既有的 `UNUSABLE` 分工：`UNUSABLE` 是「本次驾驶发现的不可用」，内存里、modeld 重启即清；黑名单是「这台机器永远不该被拨」，跨重启有效。
* 现场已落地：`/data/.jetlink_wifi_blocked` 内容 `192.168.10.36`；`/data/.jetlink_wifi_peer` 仍是 `192.168.10.65:5599`。
* 单测：`jetlink_repo/tests/test_wifi_discovery.py` **26 passed**（新增 6 例：黑名单不被探测、不被当作记住的 peer、只收地址不收端口/垃圾行、重复 block 只写一次、不可写文件不抛异常）。
* jetlink 全量：**1532 passed / 31 skipped**。

> 生效时机：`wifi.py` 由 modeld 在 join 时导入，**下次 modeld 启动**才用上新逻辑；文件本身现在就已经在盘上。

## 9. 这一轮顺带查出的两个「隐藏 bug」

1. **（已修）jetlink 测试套件会覆写设备真实的 `/data/.jetlink_wifi_peer`。**
   跑完 `pytest jetlink_repo/tests` 后该文件变成
   `<Mock name='mock.peer_host' id=...>:5599:<monotonic>`——`link.open_link` 会真的调
   `wifi.remember_peer(client.peer_host)`，而某个用例的 client 是 Mock，于是把 Mock 当主机写进了设备状态文件。后果是下一次 join 会去拨一个不存在的主机（且这条捷径会绕过 `UNUSABLE`）。
   修法：`tests/conftest.py` 加 autouse fixture，把 `PEER_FILE` / `BLOCK_FILE` 一起指向 `tmp_path`，并在首尾 `forget_unusable()`。真机文件已恢复为 `192.168.10.65:5599:`（本机 monotonic 时间戳），并复跑全量确认文件不再被改动。
2. **（未修，留作下一轮）op 助手 `:5090` 上的 `.201` 客户端在反复重连，并会压出 MB 级 send-Q。**
   20 分钟内看到 `1156 / 2075 / 3808 / 11106 / 11119 / 12786` 六个源端口先后 ESTAB（旧连接正常关闭，不是泄漏），其中 `:3808` 一次压出 **2,608,013 B** 未发出。方向也不对称：它同时往设备灌 **14.7 Mbps**（而 jetlink 上行才 26.6 Mbps）。建议下一轮给预览类 WebSocket 加背压上限（超阈值丢旧帧或断开该客户端），别让不读的对端在服务端无限缓存。

## 10. 重启后 3 条验证（新代码要重启才载入）

```bash
# ① 停车门在起作用：active=false 且 reason 带 parked
curl -s 127.0.0.1:8082/api/status | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['inferenceGate'])"
# ② CPU 从 ~24% 掉到个位数（停车 + 行车预览）
top -b -n1 -p $(pgrep -f xiaoge_data) | tail -2
# ③ 车道结果在停车时应当是 stale，起步 1 帧内恢复
curl -s 127.0.0.1:8082/api/status | python3 -c "import json,sys;d=json.load(sys.stdin)['lane'];print(d['resultFresh'], d['inference']['count'], d['inference']['lastAgeSeconds'])"
```

判据：② 从 24% 降到 ~1–2%（只余收帧/快照）；起步后 `count` 立刻恢复增长，`resultFresh` 在 `XIAOGE_LANE_TIMEOUT_NS`（4 s）内转回 true。
