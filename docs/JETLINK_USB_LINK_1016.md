# Jetlink USB 链路 —— 手机侧 NPU 真的接上了：两处断点，都在本 fork 侧（2026-10-16）

> 设备 `comma-a821bfb2`（tizi，Porsche Macan）｜openpilot `980ebfe076`（sp-macanlong-test，行车上跑的是源码树）
> jetlink `cn` `f5fe166` → 本轮 +2 提交｜上一轮：`ai/docs/JETLINK_UPSTREAM_PR_1016.md`（PR 材料）

## 0. 结论先说

**USB 链路现在通了**：modeld 借到 gadget、大模型前置准备 0.82 s 完成、手机侧 engine 报上来
（`htp-whole-SM8975`，即一加16 的 Hexagon）、大模型 swap 成功（`modelV2.big is now true`），
帧循环 warp 2.4 ms + 手机侧 19.4 ms。

用户那句「手机 app 端还是显示等待 comma」**不是上游引入的 bug**（上游 `mouxangithub/openpilot`
本轮没参与），是本 fork 侧两处断点，一处代码接口、一处构建产物：

| # | 断点 | 现象（本机日志原文） | 根因 |
| --- | --- | --- | --- |
| A | jetlink `warp.prepare_reset()` 读小模型的 `state_pairs` / `packed_input` | `AttributeError: 'ModelState' object has no attribute 'state_pairs'` → `jetlink load failed` | 那两个名字是**上游 modeld** 的形状；本 fork 的 stock modeld 是 `npy` + `input_queues`（不打包），prepare_reset 只有三种已知形状，遇到未知就抛，把整个 join 打死 |
| B | warp pickle 的格式 | `RuntimeError: warp_1928x1208_512x256_tinygrad.pkl is not a driving warp: _TinyJit` | jetlink main `0f87696`（"run modeld's own warp, not one jetlink builds"）起只认 `{'run','input_specs'}`；本 fork 的 `SConscript` 还在调 **jetlink 已被删除的 capture**（`python -m jetlink.openpilot.warp`），源码构建的 `-` 前缀把失败吃掉了，盘上留的是 10-13 编的旧格式（裸 `TinyJit`） |

两处都修掉之后链路自己就起来了 —— 手机侧 APK **不用重编**（协议没变，`libjetlink.so` 也没动）。

## 1. 现场怎么读出来的（本机日志，非记忆）

- `jetlink-owner.log` 里 20:09–21:00 每 60 s 一轮
  `nothing left to do, releasing the gadget… / presenting the gadget again / a host configured us at
  super-speed / starting a provisioning run: a jetson turned up`：
  gadget 每 60 s 断一次重枚举，说明**口上有 host（手机）在，但没人真正要这个 gadget** ——
  电池那侧就是 `DORMANT_HOLD`，而这轮循环的成因是 modeld 的 join 每次都失败（没有 borrower
  来 hold）。
- modeld 的 swaglog 给出两次真实异常，正好对应上表 A、B（见 §0 表内原文）。
- 修掉 A 之后 B 才露出来（`prepare_reset` 在 `Warp(...)` 之前，见 `joining.py:696-700`）。

## 2. 本轮改了什么

**jetlink（子模块 `cn`，两个提交）**

| 文件 | 改动 |
| --- | --- |
| `jetlink/openpilot/warp.py` `prepare_reset` | 一个**没有** `state_pairs` 的模型 = 不打包的模型，不是"无法 reset 的模型"：按 legacy bundle 的办法处理（非 NPY 队列全清 + numpy 视图清），并对本 fork 的 `npy` 名字显式认领。原先是唯一的三分支里没有第四支 → `AttributeError` |
| `jetlink/openpilot/warp.py` `init_device` | `tinygrad.engine.worker` 不存在（本 fork tinygrad pin `66ee3cfb4`）从 `log.exception`（ERROR + traceback）降为一行 warning —— 它本来就写着"an older tinygrad or PARALLEL=0 is not a failure" |
| `tests/openpilot/test_warp.py` | 新增 `test_this_forks_stock_modeld_and_its_npy_views`（NPY 上传张量不许被 assign、GPU 队列与 npy 视图都被清零、`prev_desire` 清） |

**openpilot（本 fork）**

| 文件 | 改动 |
| --- | --- |
| `openpilot/sunnypilot/jetlink_adapter/warp_build.py`（新） | 用**本 fork 自己的图**编出 jetlink 要的 pickle：`compile_modeld.make_frame_prepare`（同一条 perspective warp，上游 `tinygrad/examples/openpilot/compile_warp.py --frames 2 --layout yuv420` 等价），输入 `M_inv (2,3,3) f32` + `input_frame (2, nv12_copy_size) u8`，出 `(2,6,128,256)`，落 `{'metadata','run','input_specs'}`；临时文件 + replace，编到一半不留下 load() 会打开的名字。本机实测 **15.4 s** |
| `openpilot/sunnypilot/jetlink_adapter/SConscript` | 改调 `warp_build.py`（带 modeld 编译同款 `DEV=QCOM IMAGE=1 FLOAT16=1 NOLOCALS=1 JIT_BATCH_SIZE=0 OPENPILOT_HACKS=1`），把 `jetlink/openpilot/warp.py` 作为依赖（它变了就要重编）；保留 `-`（源码构建不吃编译失败）；不再建 lossless |

**删掉的东西**：`sunnypilot/jetlink_adapter/models/warp_1928x1208_512x256_lossless_tinygrad.pkl`
（10-13 的旧格式）。jetlink 的 `with_errors` 随 `0f87696` 一起没了，留着只会在 Wi-Fi 上
`load(lossless=True)` 直接抛；删掉后 Wi-Fi 走 raw 帧。

## 3. 实测（2026-10-16 21:00 之后，USB 模式）

```
jetlink: borrowed the gadget (udc a600000.dwc3) from the owner
jetlink: prepared the large model ahead of the swap in 0.82 s
jetlink: htp-whole-SM8975 trt None, engine none, loaded 57a3bf0c312dbf14
jetlink: link ready, waiting for a window to swap
jetlink: large model joined mid-drive, modelV2.big is now true
jetlink: frame 1 warp 2.4 data 0.5 send 1.6 wait 25.7 ms; server gpu 19.4 queue 1.4 total 20.8 ms; ffs maxima prepare 0.0 read_wait 46.9 handoff 0.2 ms
```

owner 侧：`lending the gadget to modeld` → `modeld says the server on htp-whole-SM8975 stays up when
the gadget goes (sleep_after 0)` —— 手机被当作常驻 server，60 s 的 dormant 循环随之结束。

**复现测试方法（不用重编）**：modeld 是源码树里跑的，所以改 Python 立刻生效；
`IsOnroadPreview` 关→开一次即可让 manager 重新拉起 modeld（注意：用 `pkill` 直接杀，
manager 视作 crash 且 `restart_if_crash=False`，**不会**再拉起 —— 要走 param 翻转）。

## 4. 留给下一轮

1. **Wi-Fi 链路**（用户要求两条都通）：USB 已通，Wi-Fi 待测；lossless 图目前无人能编
   （jetlink 删了 `with_errors`），先按 raw 帧跑，若要 lossless 得在 `warp_build.py` 里自建
   `(frame, med_errors)` 两输出图。
2. **上游 `mouxangithub/openpilot` `test`**：本地核查点 `8637b9ef37` → 远端 `12e5bb39fe`，
   44 个新提交（含 jetlink bump 到 main、`fix(modeld): pass chestnut to jetlink_adapter.prepare()`、
   modeldLagging 三个修复、carrot 红绿灯/信号等）。与本轮断点无关；是否合并另算。
3. **性能**：手机侧现在是 `htp-whole-SM8975` 跑 policy（19.4 ms）；「还不如上一代 8e5」的
   调优点仍在 QNN 侧，与链路无关。
