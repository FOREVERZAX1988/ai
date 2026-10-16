# JetLink 流水线 —— 8e6 的帧预算里谁在等谁（2026-10-16 夜，USB）

> 设备 `comma-a821bfb2`（tizi，Porsche Macan）｜openpilot `068895693c` + 本 fork 未提交改动
> jetlink `cn` `6b61a69` → `60ed27b`（本轮把两份待推改动提交）｜手机：一加16，USB3 super-speed
> 上一轮：`ai/docs/JETLINK_WIFI_FPS_1016.md`、`ai/docs/JETLINK_WIFI_LINK_1016.md`

## 0. 现场（本机日志原文，非记忆）

用户退出手机热点、改回 USB 与手机 app 直连后，`/data/log/jetlink-owner.log` 与 swaglog：

```
22:39:11  jetlink: lending the gadget to modeld, udc a600000.dwc3
22:39:12  jetlink: modeld says the server on htp-whole-SM8975 stays up when the gadget goes (sleep_after 0)
22:39:12  jetlink: link ready, waiting for a window to swap
22:39:13  jetlink: large model joined mid-drive, modelV2.big is now true
（到 22:45 无 demote、无 next attempt、无 held）
```

单帧预算（`jetlink: frame N warp … ms`，USB 会话）：

| 段 | 值 | 谁花的 |
| --- | --- | --- |
| warp | 2.3 – 2.7 ms | comma CPU（tinygrad，帧线程） |
| data | 0.5 ms | 组包 |
| send | 1.5 – 1.9 ms | USB3 写 393 KB（≈245 MB/s） |
| wait | 28.0 – 28.1 ms | 手机 → 回包 |
| **帧周期** | **≈ 33 ms** | 相机节拍 50 ms ⇒ 余量 17 ms |

手机侧同一帧：`server gpu 26.5 – 27.8 queue 0.4 total 27.0 – 27.2 ms`（staging 0.4 ms，
NPU 26.5+，输出转换 ≈ total − gpu − queue）。`wait − total ≈ 0.8 – 1.5 ms` 就是整个链路的往返。
USB 收包路径不是瓶颈：`ffs maxima prepare ~0 / read_wait 39（只有 join 后头两帧）/ handoff 0.2 ms`。

**结论**：USB 下 33 ms 远在 50 ms 预算内，drop 不再越过 0.75 %（Wi-Fi 那份的 54 ms 才是越线的），
帧率的瓶颈已经从链路搬到手机 NPU 自己身上——`gpu` 一项就占帧周期的 82 %。

## 1. 串行链：三处都没有重叠（这是「没做流水线」的字面意思）

1. **host**：`model_state.prepare()`(warp) → `send()` → `end()`(等回包)。同一根 modeld 帧线程，
   请求/响应深度 1；`skip_if_busy` 让发不出去的帧被跳过而不是排队，所以帧与帧之间不可能重叠。
2. **app**：`Session.serveForever()` 是单线程 `recv → stage → engine.run() → respond`，
   整次 `infer()` 还握着 `host.lock`。收下一帧、写回包都排在 NPU 之后。
3. **引擎**：`OrtEngine.execute()` 在调用线程上顺序跑 chain 里每个 session（`htp-whole` 只有一个）。

所以每帧 = warp + 组包 + 发送 +（往返 + NPU + 输出转换），谁也没盖住谁。

## 2. 可优化项（按收益/风险排，括号里是要动哪一层）

| # | 做法 | 预期收益 | 代价 / 风险 | 需要什么 |
| --- | --- | --- | --- | --- |
| A | app 侧跨帧双缓冲：算 N 时收/stage N+1，N 的输出转换与 N+1 的 NPU 重叠 | USB ~1–2 ms；**Wi-Fi ~5–12 ms**（lossless 解压记在 `queue` 里 4–11 ms） | 中：协议要允许多帧在飞（回包有 frameID，但 `host.lock` 与单套 staging 缓冲要拆双份） | 手机侧改代码 + 实机 |
| B | host 侧流水：等 N 的回包时做 N+1 的 warp/组包/发送 | ~4.5 ms（USB）/ ~7.5 ms（Wi-Fi） | 中高：要把 `model_state` 拆成生产线程 + 发布路径，且多一帧延迟。控制回路不能这么干，**preview 可以**（preview 不接管） | 只在另一套状态机上做，别碰 in_control |
| C | **NPU 图本身 26.5 ms**——「8e6 跑得慢」的真身 | 未知，可能最大 | 先取证再动 | 见 §3 |
| D | Wi-Fi 空口：`Packer` 12 个 plane 顺序压（2.1 ms）改并行（~1.5 ms 收益）、sendmsg 路径 | ~2–3 ms | 低 | jetlink 侧，只对 Wi-Fi 有意义 |

A/B 都是「把等待盖起来」的传统流水线；C 是「让每帧本身变快」。USB 现状（33 ms）说明 A/B
现在不是刚需——它们是 Wi-Fi 那 54 ms 的处方；C 对两条链路都值钱。

## 3. NPU 那 26.5 ms：先取证，再谈优化（需要手机侧）

大佬那句「不会做流水线」在 QNN 上最典型的一种落法，是**图里有算子落回 CPU**：
中间夹一个 CPU 算子 ⇒ 每帧在 HTP 与 CPU 之间往返两趟 DMA，HTP 的流水就断了
（本仓 10-15 那轮 `took no node of model` 就是同一类现象的另一端：整张图掉到 CPU）。
所以顺序应该是：

1. 取 app 的 `npu:` 报告 / QNN EP 日志：`<n> nodes are supported, <m> are not`、是否有 fallback；
   以及 `htp_performance_mode=burst` 的性能基础设施是否真的立起来了
   （`OrtBackend.providerOptions(.htp)` 已设 `burst` / `htp_graph_finalization_optimization_mode=3` /
   `enable_htp_fp16_precision=1` / `qnn_context_priority=high`，但「设了」≠「生效了」）。
2. 若确实全在 HTP：试 `vtcm_mb`（V85 的 VTCM 更大）、`offload_graph_io_quantization`、
   `enable_htp_weight_sharing` 一类 onnxruntime 1.29 的 QNN 选项，一次只改一个，记 benchmark。
3. 顺带把 `split`（vision→HTP + policy→QNN GPU）与 `htp-whole` 在同一台机上实测对比：
   两条 EP 并行是「流水线」的另一种写法，但 8e6 上未必赢过单张大图。

这些都必须在手机上量（app 的 benchmark 页或 adb），不在 comma 侧——本轮没有做，留给下一轮。

## 4. 本轮顺带做完的

- 两份待推改动落地并提交：jetlink `f477cac`（`Warps.load` 认 lossless 的 tuple 返回值）、
  `60ed27b`（`joining.run()` 的 drop 分支放过 preview，+ 回归测试）；openpilot 侧 lossless warp 的构建与用例。
- 未动、按用户意思保持不动的：preview 退出后手机 app 仍跑模型（上游 `warmIfIdle` 只在 120 s 后
  停止保温，**从不** `unload()`；`unload()` 只由客户端的 `.unload` 指令走 ⇒ 跟随上游）。
