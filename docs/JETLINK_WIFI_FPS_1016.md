# JetLink Wi-Fi 链路 —— fps 上不去（<20）与模型反复掉线：本 fork 丢了 lossless 帧（2026-10-16）

> 设备 `comma-a821bfb2`（tizi，Porsche Macan）｜openpilot `068895693c`（源码树，行车上跑）
> jetlink `6b61a69`（+1 本地提交：loader 认 tuple ret）｜手机：一加16，热点 `OnePlus 16`，5GHz ch36，
> comma 侧 `wlan0` 433 Mb/s，`iw dev wlan0 get power_save` = 0

## 0. 结论先说

「手机 app 模型在跑但 fps 上不到 20」在设备上是两件事叠在一起，都在本 fork / 链路上，不在上游：

| # | 现象（本机日志原文） | 根因 |
| --- | --- | --- |
| A | `frame N warp 2.4 data 0.5 send 1.8 wait 50.5 ms; server gpu 26 queue 0.4 total 27 ms` → 单帧 55 ms（≈18 fps） | **Wi-Fi 走的是 raw 帧（393 KB/帧）**。上游 Wi-Fi 的设计是 lossless 帧（MED+zstd，实测 2.1x → 183 KB），jetlink 的 `joining.py` 也是这么写的（`lossless = wifi and is_cached(..., lossless=True)`），但本 fork 的 `warp_build.py` 只会编**单输出**的 warp，`Warp.errors` 恒为 None ⇒ `model_state` 不建 Packer ⇒ 每帧多背 ~7 ms 空口时间 |
| B | `modeld dropped 0.87~1.12 % of camera frames behind the large model` → `next attempt in 1/5/10/20/40/60 s (failure N, link held X s)` | 帧周期 ~50 ms、略超相机 20 Hz 节拍 ⇒ modeld 掉 ~0.9% 相机帧 > `DROP_LIMIT` 0.75% ⇒ **大模型被 demote**；每次只活 1–5 s（< `STABLE_SECONDS` 60 s）⇒ 退避翻倍到 60 s。用户看到的就是「跑一下停很久」 |
| C | （潜在）lossless 帧根本装不上 | jetlink 的 `Warps.load()` 用 `getattr(captured.ret, 'shape')` 判形状，而 lossless 的 capture 返回 **tuple** `(frame, med_errors)` ⇒ `()` ≠ `(2,6,128,256)` ⇒ 抛 `the warp makes (), not a 512x256 model's input`。0f87696 把 warp 构建器删掉时漏了这一支（`Warp` 类本身是认 tuple 的） |

## 1. 现场怎么量出来的（本机，非记忆）

- **帧预算**（22:00–22:06，raw）：`warp 2.4 + data 0.5 + send 1.8 + wait 50.5 ≈ 55 ms`，`server total 26 ms`
  ⇒ 非服务端时间 ≈ 25 ms = 上行（393 KB ≈ 13 ms @ ~28 MB/s）+ 往返（RTT ~11 ms）+ jitter。
- **网络本身**：comma→手机热点 `ping` min 0.98 / mean 10.8 / max 28.9 ms（mdev 10.9）；TCP 5599 握手
  min 3.1 / mean 11.1 / max 23.6 ms。链路能到 433 Mb/s，但**手机热点的时延与抖动就是 10 ms 量级**。
- **modeld 掉帧**：`modeld dropped 0.87/0.92/0.96/0.97/0.98/1.01/1.12 %`，全部落在 `DROP_LIMIT`(0.75%) 之上。
- **退避链**：`next attempt in 1 s (failure 1, link held 1 s, drop 0, lag N this drive)` → 1/1/5/10/20/40/60 s
  （`QUICK_RETRIES` 3 次 1 s，之后 `REJOIN_DELAY` 5 s 起翻倍；link held < 60 s 就重置不了 streak）。
- **单帧最慢一次** `send 57.2 ms`（22:06:33）：183 KB 塞不进内核发送缓冲时的反压，空口确实是瓶颈之一。

## 2. 本轮改了什么（4 个文件 + 1 个 jetlink 提交）

**openpilot（本 fork）**

| 文件 | 改动 |
| --- | --- |
| `openpilot/sunnypilot/jetlink_adapter/warp_build.py` | 新增 `with_errors(graph)`（把 jetlink 的 `jetlink.openpilot.lossless.med` 接在同一张图上）与 `--lossless`：capture 返回 `(frame, med_errors)`，`Tensor.realize` 两个输出都 realize。单输出路径一字未动 |
| `openpilot/sunnypilot/jetlink_adapter/__init__.py` | 新增 `lossless_warp_path()`：按 jetlink 自己的命名规则（`lossless_path`）把 `_lossless_` 插在 `_tinygrad.pkl` 前，保证 build / load 用同一个名字 |
| `openpilot/sunnypilot/jetlink_adapter/SConscript` | 每个相机在 plain warp 之外多编一个 lossless warp（`--output <lossless> --lossless`）；submodule 有 `jetlink/openpilot/lossless.py` 才编，没有就只编 plain。子命令 PYTHONPATH 里额外加上 `jetlink_repo`（root 之外），prebuilt runner 上 `import jetlink` 也成立 |
| `openpilot/sunnypilot/jetlink_adapter/tests/test_warp_build.py` | 3 个过期用例（还在断言旧的 `python -m jetlink.openpilot.warp --adapter`）改成现在的 builder；新增 `test_the_lossless_warp_loads_through_jetlinks_own_reader`：在 CPU 上真编一次 `--lossless`，再交给 jetlink 的 `Warps.load()` 读（就是这条能挡住 §0 表 C） |

**jetlink（子模块 `6b61a69` +1 本地提交，待推到 `FOREVERZAX1988/jetlink`）**

| 文件 | 改动 |
| --- | --- |
| `jetlink/openpilot/warp.py` `Warps.load` | 形状检查改成先取 `ret[0]`（`isinstance(ret, (tuple, list))` 时），再 `getattr(..., 'shape')`：单输出路径行为不变，lossless 的 tuple 也能进 |

**设备上编出来的产物**：`openpilot/sunnypilot/jetlink_adapter/models/warp_1928x1208_512x256_lossless_tinygrad.pkl`
（1.4 MB，QCOM 上 20 s 编完）。`Warps.is_cached(..., lossless=True)` 现在为真，`joining.prepare()` 的
`lossless = wifi and …` 于是成立；USB 仍然只加载 plain warp（`lossless` 只在 `wifi` 时置真）。

## 3. 实测（本机，同一手机同一热点）

| 会话 | fps | warp | data | send | wait | server total | drop% | link held |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 22:00:06（raw） | 19.5 | 2.4 | 0.5 | 1.7 | 47.7 | 26.6 | 0.87 | 4 s |
| 22:03:23（raw） | 16.3 | 2.5 | 0.5 | 1.4 | 51.0 | 26.9 | 0.95 | 2 s |
| 22:05:27（raw） | 19.4 | 2.4 | 0.5 | 2.0 | 50.5 | 27.6 | 0.90 | 5 s |
| 22:08:27（lossless） | 19.9 | 2.4 | 0.7 | 4.4 | 47.0 | 26.6 | 1.12 | **40 s** |
| 22:09:13（lossless） | 19.9 | 2.4 | 0.7 | 4.5 | 47.0 | 27.2 | 0.92 | **44 s** |
| 22:10:30（lossless） | 19.9 | 2.4 | 0.7 | 4.4 | 47.8 | 29.2 | 0.92 | 12 s |

> 表里 `warp/data/send/wait` 是**被记下来的慢帧**（`>SLOW_FRAME` 50 ms 或 held）的中位数，快帧不记，
> 所以不能直接相加当帧周期；`fps` 是 `Δframe_id/Δt`，即 modeld 真实节拍。

- lossless 生效的证据：`send` 1.7→4.4 ms（多出来的就是 12 个 plane 的 zstd 打包，设备上 bench 实测
  p50 2.1 ms），`wait` 50.5→47 ms，**app 侧 fps 18 上下 → 19.9**。
- `send` 打包成本 +2.6 ms 是**串在帧线程上**的（jetlink 的 `Packer` 12 个 plane 顺序压），它抵掉了一部分
  省下来的空口时间；净收益 ~2–3 ms。
- 手机侧 `total` 没降（26.6 ms 不变，另几次 27–32）：帧小了，但手机多了一次 lossless 解码（记在
  `queue` 里，0.4→4–11 ms），一进一出基本抵消。
- 22:08–22:18 连看 10 分钟（13 段会话，共 joined 206 s）：fps 19.2–20.0（多数 19.9/20.0），
  `send` 4.2–4.6，`wait` 44.6–47.8，drop 0.79–1.12%，单段存活 2/3/4/7/10/12/13/40/44/**59** s。
  也就是说：**帧率够了，但还没跨过 `STABLE_SECONDS` 60 s**，streak 照旧累加。
- **正确性**：lossless build 的第一个输出与 plain build 的帧**逐字节相同**（0 差异；同一 nv12 输入、
  同一 M_inv，在设备上对跑两个 pickle）。所以 USB 走 plain 不变；万一手机不认 `med-zstd`，
  走 lossless build 的第一输出也还是同一张帧。

## 4. 还没解决的（要做决定）

**现在链路能连 ~40 s 了（原来 1–5 s），但 `modeld dropped ~0.9%` 仍会周期性越过 `DROP_LIMIT` 0.75%
把大模型 demote。** 40 s < `STABLE_SECONDS` 60 s，所以 streak 照样累加、退避照样翻倍——长时间跑还是
「跑 40 s 停 1 s，几轮之后停 10/20/60 s」。

缺多少：帧周期 ≈ warp 2.4 + data 0.7 + pack/send 4.4 + wait ~44.5 ≈ 52 ms，相机节拍 50 ms ——
**还差 2–3 ms** 才能把 drop 压到 0.75% 以下、并让单段活过 60 s。要真正稳住，只有两条路
（都建议先和上游对一下，不擅自改）：

1. **给 drop 规则加 Wi-Fi / preview 的口径**。`joining.run()` 里这一支是唯一的「与链路无关」的健康门槛：
   它存在的理由是「别让 modeld 的 frameDropPerc 越过 selfdrived 的 1% 软退出（modeldLagging）」——
   而 preview 里没有任何东西能被控制，`in_control` 恒 False；`model_state._note_hold` 里这套理由已经
   写成 preview 例外（"it never takes control, so a host that is slow but answering is the feature"），
   `run()` 的 drop 支却漏了。链路已经有 per-link 常量（`WIFI_HOLD_FRAME`/`CABLE_HOLD_FRAME`），
   加一个 `WIFI_DROP_LIMIT` 也是同一种写法。
2. **再挤 2–3 ms 出来**（把帧压到相机节拍以下）：`Packer` 12 个 plane 并行压（现在顺序，实测 2.1 ms，
   并行大约能省 1.5 ms）、sendmsg 路径（183 KB / 2.3 ms）——都是 jetlink 侧的活。

另外两条与链路无关但更值钱的：手机侧 NPU `gpu 22–29 ms`（QNN 调优那条待办），以及热点本身的
RTT/jitter 10 ms 量级（手机亮屏/前台/充电会更稳；换 Mac/Jetson 热点时延会低一个数量级）。

`openpilot/sunnypilot/jetlink_adapter/tests/` 全套 112 passed / 4 failed / 5 errors：其中 5 个 error 是
`test_tinygrad.py` 的 setup 还在 `from jetlink.openpilot.warp import call_warp`（jetlink 0f87696 删了它），
3 个 fail 是 chestnut 告警文案 / policy queues / seam 表，都与本轮改动无关，属 jetlink pin 前进后没跟上的旧账。

## 5. 复验步骤

1. 编 lossless warp（设备上，20 s；源码树里 modeld 立刻可用，卡住的只有下一次 join）：
   ```
   cd /data/openpilot
   env PYTHONPATH=/data/openpilot DEV=QCOM IMAGE=1 FLOAT16=1 NOLOCALS=1 JIT_BATCH_SIZE=0 OPENPILOT_HACKS=1 \
     python3 -m openpilot.sunnypilot.jetlink_adapter.warp_build \
     --camera 1928x1208 --model 512x256 \
     --output openpilot/sunnypilot/jetlink_adapter/models/warp_1928x1208_512x256_lossless_tinygrad.pkl --lossless
   ```
2. 让 modeld 重新 join 就会去读它（`is_cached` 每次现查，无需重启）；要连 jetlink 的 loader 补丁一起生效，
   得重拉 modeld：`IsOnroadPreview` 0→1（manager 会重启 modeld；**别用 pkill**，manager 视作 crash 且
   `restart_if_crash=False`）。
3. 看日志：`send` 应到 ~4.4 ms、`wait` 应到 ~47 ms；`grep "jetlink: frame" /data/log/swaglog.*`。
4. 验收：`grep "next attempt in" /data/log/swaglog.*` —— lossless 之前每 1–5 s 一条，之后应稀疏到 40 s 量级。
