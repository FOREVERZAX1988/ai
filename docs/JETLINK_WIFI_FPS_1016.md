# Jetlink Wi-Fi —— 帧循环到底慢在哪：不是 8e6，是没有重叠（2026-10-16）

> 设备 comma-a821bfb2（192.168.10.79）｜jetlink `cn` @ `60ed27b`｜素材：`/data/jetlink_recent.txt`
> 起因：用户「开了 Wi-Fi 链路 + 行车预览，手机 app 进模型工作模式，fps 很低，到不了 20」；
> 有意见认为「8E6（SM8975）跑得慢是因为不会做流水线优化」。

## 0. 结论先说

**手机那颗芯片不慢，它在闲置。** 2026-10-16 21:29–21:46 的 Wi-Fi 会话，637 条帧日志的统计：

| 量 | 中位数 | 说明 |
| --- | --- | --- |
| `warp` | 2.5 ms | comma 侧 GPU 变形 |
| `data` | 0.6 ms | CPU 打包 |
| `send` | 1.8 ms | 提交给传输层 |
| **`wait`** | **50.5 ms** | `infer_end` 实际等了多久（预算 55 ms = `WIFI_HOLD_FRAME`） |
| `server gpu` | 25.1 ms | 手机端自己报的推理时间 |
| **`server queue`** | **0.4 ms** | **手机端排队时间 —— 加速器 99% 时间是空的** |
| `server total` | 25.7 ms | gpu+queue |

- `wait` 中位数 **50.5 ms**，恰好压在 55 ms 预算上；同一批日志里 **396/637 帧被 held**
  （预算内没等到答复 → 发布上一帧的输出）。
- 账算不平的部分：`wait - (warp+data+send+server total)` 中位数 **19.7 ms**，
  即**传输 + 手机 app 侧收发/编组**的净开销，它不体现在 `server total` 里。
- 也就是说：**一帧 = 2.5 变形 + 1.8 提交 + ~20 传输 + 26 推理 ≈ 51 ms**，
  而相机周期就是 50 ms（20 Hz）。**零余量** → 每隔一帧就 held。
- 会话末尾的判罚印证了这条链：`modeld dropped 0.95 % of camera frames behind the large model`、
  `next attempt in 40 s (failure 7, link held 4 s, drop 1, lag 13 this drive)`、
  `jetlink fell behind ... the small model drives from this one` —— 大模型被交还给小模型。

长跨度实测（就是相机速率，说明帧循环**顶在**相机节拍上，没有自己的余量）：

| 区间 | 跨度 | 帧 | 速率 |
| --- | --- | --- | --- |
| 21:31:48 → 21:32:21 | 33 s | 1..651 | 19.7 fps（50.8 ms/帧） |
| 21:34:55 → 21:35:40 | 45 s | 1..905 | 20.1 fps（49.8 ms/帧） |
| 21:43:48 → 21:45:08 | 80 s | 1..1595 | 19.9 fps（50.2 ms/帧） |

## 1. 帧路径是严格串行的（`JetlinkModelState.run`）

`model_state.py`: `run()` = `prepare()` → `send()` → `end()`，而 `end()` 里
`client.infer_end(frame.seq, hold=self._hold_left(frame))` **阻塞 modeld 的帧线程**。
于是稳态里**只有一帧在飞**，三段时间完全相加：

```
[comma 变形+打包 5ms] -> [传输上行] -> [手机推理 26ms] -> [传输下行]   = ~51 ms
```

`client.py` 其实**已经**具备多帧在飞的能力（`_in_flight: deque`、`infer_begin` 立刻返回
seq、`infer_end(seq, deadline=...)` 按 seq 取回复），目前只用它来在等 Jetson 时发布
`chestnutState`（`after_enqueue`）。**所以流水线是接线问题，不是协议问题。**

## 2. 可做的优化（按收益/风险排序）

1. **让链路常驻一帧在飞（流水线）**：帧 N 的 `infer_end` 不再为 N 自己阻塞，而是
   发布 N-1 的回复、并把 N 立即发出去。稳态周期从
   `comma + 传输 + 手机`（~51 ms）降到 `max(comma+上行, 手机) + 下行`（~30-35 ms）。
   **延迟不变**：今天 held 帧发布的也是一帧旧的 plan；流水线只是让每一帧都拿到自己的新回复，
   于是 `held` 与 "fell behind" 的判罚不再触发，大模型不再被交还。
   （`_hold_frame`/`_holds_in_a_row`/`_holds_allowed` 的整套判罚本来就是为「一帧在飞」写的。）
2. **确认 lossless 真的协商上了**：`client.takes_lossless` 取决于 hello 里的
   `frame_codecs`（`P.LOSSLESS_CODEC`）。lossless 是「半个帧的字节，给 Wi-Fi」——
   而 `warp_1928x1208_512x256_lossless_tinygrad.pkl` **已经在**
   `sunnypilot/jetlink_adapter/models/`。没协商上的话，那条 ~20 ms 的传输项就是两倍字节。
3. **把 comma 的 CPU 抢回来**：这是最便宜的。同一时刻 load average **8.9**，
   `ai.aid`（我们自己的助手守护进程）**74 % CPU**、`xiaoge_data` 77.8 %、`models.manager` 51.9 %。
   日志里 `send` 中位 1.8 ms 但**最大 125.6 ms**，`warp` 中位 2.5 ms 但**最大 22.9 ms** ——
   这些尖刺就是被抢 CPU 抢出来的，也正是把「余量本来就 0」的一帧推过预算的那一下。
4. **Wi-Fi 本身**：`WIFI_HOLD_FRAME = 0.055` 是拿 55 ms 窗口去覆盖实测 ~45 ms 的回复；
   同一条链路 USB 实测 19.4–25 ms。真上路优先 USB；Wi-Fi 只适合预览/取证。

## 3. 顺带记下的两件事实（本轮未改）

- `HOLD_FRAME = 0.046`（USB/默认）、`CABLE_HOLD_FRAME = 0.05`、
  `WIFI_HOLD_FRAME = 0.055`、`INFERENCE_TIMEOUT = 0.2`。
- `modeld` 每帧打印的 `queue` 中位 0.4 ms —— 这就是「8e6 不慢」的直接证据。
