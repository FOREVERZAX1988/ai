# Jetlink Android NPU —— G 轮：把手机自带那套 2.48.5 装进 APK（2026-10-16）

> 设备：Snapdragon **SM8975** / ColorOS 17 / OPPO PYB110（一加16），无线 adb
> `192.168.10.65:44757`（端口每次变，配对见用户当次给的信息）
> 仓库 `FOREVERZAX1988/jetlink` `cn` @ `fa48c11`（origin/cn 已是此点，本地
> remote-tracking 陈旧显示 ahead 2，`git ls-remote` 核实一致）
> 前一轮：`ai/docs/JETLINK_ANDROID_NPU_NAME_1016.md`（方向 3+1）

## 0. 本轮做了什么（用户一句：`拉 2.48.5`）

1. **把手机自带那套 QNN 拉全**。上一轮只 adb pull 了四件，缺
   `/odm/lib64/libQnnHtpPrepare.so`（88 MB）。本轮补齐：

   | 手机文件 | 落地 | bytes | 版本 |
   | --- | --- | --- | --- |
   | `/odm/lib64/libQnnHtp.so` | `work/_probe/libQnnHtp.so` | 3,778,744 | v2.48.5.260901221701 |
   | `/odm/lib64/libQnnHtpPrepare.so` | `work/_probe/libQnnHtpPrepare.so` | 88,128,192 | v2.48.5.260901221701 |
   | `/odm/lib64/libQnnSystem.so` | `work/_probe/libQnnSystem.so` | 4,052,904 | （无版本串） |
   | `/odm/lib64/libQnnHtpV85Stub.so` | `work/_probe/libQnnHtpV85Stub.so` | 779,448 | v2.48.5.260901221701 |
   | `/odm/lib/rfsa/adsp/libQnnHtpV85Skel.so` | `work/_probe/libQnnHtpV85Skel.so` | 12,582,764 | v2.48.5.260901221701 |

   五件一套，全 v2.48.5.260901221701（对照我们的是 v2.51.40.260930230134）。
   另：`/odm/lib/rfsa/adsp/libQnnHtpV85.so`（12,931,988）是给 **DSP 侧**用的
   后端，APK 里不需要带（APK 带的是 host 侧 `libQnnHtp.so`）。

2. **用它出一版 APK**（不改代码，只换 APK 里那五个 entry，做法与
   `cn-204f17c` / `cn-2ad8f63` 的 matched 版一致）：

   ```
   http://192.168.10.79:8012/0.8.7-1016-3-vendormatched/app-release-vendormatched.apk
   109,945,682 B   sha256 2b2a53dcfc6c6b11dd6b7e839face921917d6531db7d5c7ace18e994c857703a
   ```
   - base = `0.8.7-1016-3-pairdiag/app-release-pairdiag.apk`（我们 2.51 那套）；
     `libjetlink.so` 仍是 `ac43360a3754ddf7`（= 0.8.7-1016-3，含方向3 的报告）。
   - 换掉的五个正是手机那套 2.48.5；其余 162 个 entry 与 base 逐字节相同
     （含 AAR 的 V68..V81 Stub+Skel）。
   - 证书 `043da762…`（同手机在装版本）⇒ **覆盖安装**。
   - 驱动：`work/inject_matched.py`、apksigner r35、JRE `work/jre`。
   - 版本 staging 在 `/data/media/qnn-v85-v248/`（对照 2.51 的在 `/data/media/qnn-v85/`）。

## 1. 为什么这一版值得测（验证什么 / 证伪什么）

手机侧日志里，用我们 2.51 的 Skel：

```
remote_handle64_open: RPC NPU scheduler enforcement enabled for domain 3
  via uri file:///libQnnHtpV85Skel.so?qnn_2_51_40_skel_handle_invoke&...
WARNING: get_handle_priority_from_uri: libQnnHtpV85Skel.so lib opened handle without priority token
Error 0x1: remote_work_control failed ... domain 3 (errno Permission denied)   x3
```

- 2.51 的 QNN **有** `qnn::IScheduler` / `NpuSchedulerFactory`；2.48.5 的**没有**
  （上一轮已逐文件核实）。URI 里的 `qnn_2_51_40_skel_handle_invoke` 与
  `scheduler enforcement` + `priority token` 都是**这一代才有**的东西。
- 换成本机自己的 2.48.5 Skel 后，handle URI 会变成
  `qnn_2_48_5_skel_handle_invoke`，FastRPC 不再要求 priority token。
  **这是唯一还没测过的「2.51 对 2.48.5」假设**（S6.2）。

读法：
- 若出现 `the QNN provider took no node` 消失 / 写出 EP context / 报告里
  `the HTP architectures this build carries` 那行如常 → 门被打开。
- 若仍 `took no node`，看 `remote_work_control` 还在不在：
  - 还在 ⇒ 是 unsigned-PD / sepolicy 层（`/dev/fastrpc-cdsp` 对 untrusted_app
    的 avc denied），换 build 越不过，只剩 root / 厂商门。
  - 不在、换成 `Failed to get QNN interface` 之类 ⇒ 是 **ORT 1.29 的 QNN EP
    按 ~2.42/2.51 编**、对不上 2.48.5 的接口 —— 那就是「接口版本」问题，
    需要按 2.48.5 重编 EP，而不是换库。

## 2. 一个必须知道的副作用

这一版把 host 侧五件都换成 2.48.5，而 AAR 的 **V68..V81 Stub+Skel 还是 2.51**。
V85 这台（一加16）全 2.48.5，自洽；**pre-V85 的机器**会变成
2.48.5 backend 配 2.51 的 V81 pair ⇒ 那些机器 NPU 会坏（它们本来也只有 GPU）。
发布版（releases 上的）不动，仍是 2.51 全自洽。

## 3. 用户问的两件事（回答）

1. **「卡在固件/安全策略（设备节点 + sepolicy + DSP 的 unsigned-PD/scheduler
   token），有什么办法？比如 root？」**
   - 若本轮 2.48.5 仍被 `remote_work_control` 拒：**只有 root** 能改 sepolicy /
     换域 / 给 `/dev/fastrpc-cdsp` 放行；APK 侧无解。
   - 不 root 的另一条门是**走厂商自己的服务**：NNAPI（`libneuralnetworks.so` 在
     公开库表里）或 Play 的 **LiteRT-NPU Qualcomm dispatch**，由 system_server
     代跑，绕开 app 自己的 FastRPC 拒绝。代价是另一套 profile，不是 QNN 直连。
2. **「原作者的 APK 一直加载中不报错」** —— 那是 upstream 在 GPU/CPU 上硬跑大模型
   （每帧分钟级）的表现，不是 NPU 路径；NPU 路径上游也一样过不去这道门。

## 4. 安装与读日志

```
# 无线 adb（开 Accelerator Link 会关掉 USB 上的 adb，取证一律走无线）
adb install -r app-release-vendormatched.apk
# 设置里 Phone's Own QNN 必须 = OFF（这一版的意义就是"app 自带的就是手机那套"）
```

日志里新增/该对的几行（方向 3 已带）：
- `the QNN builds in question, as the files say of themselves` → 应显示
  `v2.48.5.260901221701` 且 `IScheduler` 一栏为**无**（证明换成功）。
- `the QNN backend this run loads:` → `the app's own libQnnHtp.so, beside the app`。
- `the DSP looks for its Skel in …/lib/arm64 first, and finds:` → 现在是 2.48.5 的
  `libQnnHtpV85Skel.so`（12,582,764）。

## 5. 结果（2026-10-16 用户回报）

**调通了。** 把 host 侧五件换成手机自带那套 2.48.5 之后，QNN 不再被
`remote_work_control` / priority token 那道门拒 —— **NPU 调用成功**，
S6.2 那条唯一没测过的假设成立：卡点是 **2.51 的 Skel 与这台机器的
FastRPC 后端对不上**，不是 sepolicy / 设备节点（§1 读法里两分支取前者）。

- 性能**现在还不如上一代 8e5**，原因未定（用户判断「哪里还没弄对」），
  列为待查；先以「能跑」为这一轮的成果。
- 留档限制：本机**没有**这一轮的设备侧日志，以上据用户当次回报记录。
  下次接上设备（无线 adb）应把 `npu:` 报告三段（`buildFacts` /
  `publicTables` / `mappedPaths`）与 EP context 那几行一起存盘，再谈性能。
