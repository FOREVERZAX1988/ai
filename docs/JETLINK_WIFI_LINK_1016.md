# Jetlink Wi-Fi 链路 —— 「等待 comma」与 fps 偏低是同一件事（2026-10-16 夜）

> 设备 `comma-a821bfb2`（tizi）｜openpilot `068895693c`（sp-macanlong-test）
> jetlink `cn` `6b61a69` + 本轮 1 个改动（joining 的 preview 豁免）
> 上一轮：`ai/docs/JETLINK_USB_LINK_1016.md`（USB 两处断点）

## 0. 结论先说

用户的两句「手机 app 还是显示等待 comma」和「Wi-Fi 下 fps 达不到 20」**是同一个原因**：
大模型每次 join 之后 1–4 秒就被 `_demote(BEHIND)`，然后等 60 秒 backoff。
join 只活几秒 ⇒ app 大部分时间停在「等待 comma」；活着的几秒也只有 16 fps 上下。

**不是上游引入的**（上游 `mouxangithub/openpilot` `test` 仍是 `12e5bb39fe`，
与 `JETLINK_USB_LINK_1016.md` §4 核查时同一 tip，本轮没动）。

## 1. 现场证据（本机 swaglog + /data/log，非记忆）

- 30 分钟内 **40 次 join**、**35 次 demote**、全部 `next attempt in 60 s`：
  ```
  22:18:51  htp-whole-SM8975 trt None, engine none, loaded 404a18cfd86d2963
  22:18:51  link ready, waiting for a window to swap
  22:18:51  large model joined mid-drive, modelV2.big is now true
  22:18:57  modeld dropped 0.87 % of camera frames behind the large model, ...
  22:18:57  next attempt in 60 s (failure 14, link held 6 s, drop 0, lag 14 this drive)
  22:18:57  jetlink fell behind, port sees no host (cc 0)
  ```
- 35 次 demote 的**触发分支统计**：`modeld dropped X %` **35 次**，
  `large model held ...`（lag 分支）**0 次**，`no answer for ... s`（preview 静默）**0 次**。
  ⇒ 全部是 `_frame_drop_ratio > DROP_LIMIT`（`DROP_LIMIT = 0.0075`）。
- 打印出来的比例全是 **0.87–1.01 %**：`frame_drop_ratio = d/(1+d)`，
  `d` 是 modeld 的 FirstOrderFilter（10 s @20 Hz，α≈0.005），
  所以 0.9 % ≈ **只丢了两个摄像头帧**。上游注释写的就是「one dropped frame is forgiven,
  a second within about 6.5 s is not」。
- 帧循环本身（Wi-Fi 会话，`send ≈ 4.0–4.4 ms` 是 Wi-Fi，`≈0.5–0.7` 是 USB）：
  ```
  warp 2.48  data 0.81  send 4.23  wait 47.03  (ms, mean)
  server gpu 24.57  queue 3.26  total 27.87
  57 % 的帧是 held（held = 回包晚于 hold 期限）
  帧周期 p50 = 61–86 ms ⇒ 12–16 fps
  ```
  ⇒ 帧周期 ≈ warp+data+send+wait ≈ 54 ms，**超过 20 Hz 的 50 ms 预算**，
  所以 modeld 每隔几帧就跳过一帧摄像头帧，`_frame_drop_ratio` 越过 0.75 %。
- 链路是 **5 GHz、433 Mb/s**（`wpa_cli status`: `freq=5180, ieee80211ac=1,
  ssid="OnePlus 16"`），**带宽不是瓶颈**（send 只占预算 8 %）。慢的是**往返时延**。

## 2. 根因：drop 计数是给方向盘写的规则，preview 没被豁免

`jetlink/openpilot/model_state.py` 里 `_note_hold` 的注释是明确的意图：
> A preview is held to PREVIEW_SILENCE instead, and **to nothing else**: it never
> takes control, so a host that is slow but answering is the feature.

join 那边也照此办了（`joining.PreviewEndsTest` 那套），但 `joining.py` 的
`run()` 里另有一条**同样「写给方向盘」的规则漏了 preview**：

```python
elif self._active is not self._small and self._frame_drop_ratio > DROP_LIMIT:
```

preview 永远不会接管，被慢但答话的 host 拖着恰恰是 preview 的本意；
可这条却让大模型在 join 后几秒就交回小模型，并进 60 s backoff。

### 本轮改动（jetlink `cn`，1 处代码 + 1 个测试）

| 文件 | 改动 |
| --- | --- |
| `jetlink/openpilot/joining.py` `run()` | drop 那条加 `and not getattr(self._active, 'preview', False)`，与 `_note_hold` 的 preview 豁免对齐 |
| `tests/openpilot/test_joining.py` | 新增 `LagTest.test_a_preview_keeps_a_host_that_is_slow_but_answering`（preview 下 `skipped=2` 跑 60 帧仍由大模型驱动、不 hand back、不 reset）|

实测：`unittest discover tests/openpilot -p test_joining.py` **63 tests OK**；
把补丁回退后新测试**失败**（`{'from':'small'} != {'from':'big'}`）⇒ 是真回归测试。
`ruff check` 两个文件都过。

## 3. 还没做完的（真正的下一层）

补丁只让 preview 不被误降级，**帧周期仍然是 ~54 ms > 50 ms**，所以：

1. **往返时延要压**。组成：comma 侧 7.5 ms + 手机侧 `total` 27.9 ms + 链路/App 约 20 ms。
   20 ms 的纯链路开销对 5 GHz 本地热点偏大（USB 那份是 ~33 ms，也偏大），
   下一步要查手机 App 的 socket 循环是否被预览渲染挡着、以及 Wi-Fi 省电（PSM）是否开着。
2. **要按真流程验**：`IsOnroadPreview` 关→开让 manager 重拉 modeld，
   再看 `large model joined` 之后是否还能活过 60 s、`held` 是否降下来。
3. USB 侧同一条 drop 规则也会命中（USB 会话 `wait ≈ 56–90 ms`，比 Wi-Fi 还高），
   所以「手机显示等待 comma」在 USB 下同样有份。

## 4. 顺带回答用户的两个问题

- **`warmIfIdle` / `warmFor(120s)` 会不会顺手 `unload()`**：上游**没有**这个逻辑。
  `JetlinkKit/Sources/JetlinkServer/EngineHost.swift:465-489` 里 `warmIdleAfter=5`、
  `warmFor=120`，用途是「120 s 之后**停止保温**」（注释原文：its rejoin backs off to
  60 s, and a parked comma should not cost the battery all night），
  `warmIfIdle` **从不调用 `unload()`**；`unload()` 只由客户端 `.unload` 指令走
  (`ServerController.swift:277`)。⇒ 跟随上游 = 这一段不动。
- **熄火后手机 app 还在跑模型**：这是设计使然（`modeld says the server on
  htp-whole-SM8975 stays up when the gadget goes (sleep_after 0)`），
  按用户「先不处理这个小问题」不动。
