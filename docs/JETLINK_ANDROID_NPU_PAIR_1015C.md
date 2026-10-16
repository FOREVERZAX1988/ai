# Jetlink Android NPU —— 10-15 C 轮：backend_path 与 backend_type 互斥，app 的 SELinux domain（2026-10-15）

> 设备：Snapdragon **SM8975**（jetlink `cn`）。素材：上轮 `cn-14bbcb4` 的
> pairdiag APK，20:08 两份日志（Phone's Own QNN 关 / 开）。

## 0. 20:08 那份日志的两个结论

1. **QNN 开关「开」时那句报错不是 QNN 说的，是我们写的 provider 选项让 onnxruntime
   在构造函数里就抛了**：

   ```
   qnn_execution_provider.cc:356 QNNExecutionProvider::QNNExecutionProvider(...)
   Only one of 'backend_type' and 'backend_path' should be set.
   ```

   → 打开 Phone's Own QNN 后 ORT 连模型都没读到。前两轮把「开/关两套 pair 的失败
   方式」当对比，是无效样本。
   根因：`OrtBackend.providerOptions(.htp)` 恒设 `backend_type=htp`，给了
   `backend_path` 之后两者并存。**修法：有 path 就不给 type**（`cn-911685d`）。

2. 手机自带那套**在 app 的 namespace 里根本打不开**，linker 说得很直：

   ```
   libQnnHtp.so / libQnnHtpV85Stub.so / libQnnHtpPrepare.so / libQnnSystem.so
   is not accessible for the namespace: [name="clns-9", ...]
   opened by path before the session ... (would not open) ×4
   ```

   → 即便修掉 1，`backend_path=/odm/lib64/libQnnHtp.so` 也只会换个说法失败：
   sideload 的 app 进程够不到 `/odm`。这一条是 phone-own 路在本机上的墙。

## 1. DSP 侧：H1 的一半，日志自己已经答了

同一份日志（QNN 关，走 app 自带的 unsigned pair）：

| 行 | 读法 |
| --- | --- |
| `avc: denied { open } for path="/dev/fastrpc-cdsp" scontext=u:r:untrusted_app_34` | app 域不许直接开 DSP 节点；adsprpc 兜底走 HAL（`open thru HAL` 成功） |
| `Error 0xd: open_shell failed for domain 3 ... (errno Permission denied)` | **unsigned PD 建不起来**（open_shell 正是 unsigned PD 的入口） |
| `Error 0x1: remote_work_control failed ... domain 3 (errno Permission denied)` ×N | 句柄开了、Skel 载上了（63 ms），但向 CDSP 下发 work 被拒 |
| `RPC NPU scheduler enforcement enabled for domain 3` / `opened handle without priority token` | 这代固件的 FastRPC 带 NPU 调度器强制，且我们没有它要的 token |
| `libc: Access denied finding property "persist.vendor.fastrpc.process.attrs" / ".clockvote"` | 存在「进程属性」门（allowlist），而这个 app 不在其中 |

→ 结论：**不是缺 V85、不是 QNN 版本、不是算子**，是这个 app 进程被手机的
FastRPC/NPU-scheduler 策略拒绝 unsigned PD / work control。要再区分「所有第三方 app
都被拒」还是「只有未签名/未授权 app 被拒」，就只剩 方案A 那三条 adb 命令。

## 2. 这轮改了什么（`cn-911685d`）

| 改动 | 位置 |
| --- | --- |
| QNN 的 backend 由 path **或** type 二选一：有 path 就不给 `backend_type: htp` | `JetlinkORT/OrtBackend.swift` |
| 报告新增 `this app's SELinux domain, as the kernel reads it:`（`/proc/self/attr/current`），即每一条 `avc: denied` 的主语 | `JetlinkServer/HostDiagnostics.swift` |
| 断言 path/type 互斥、`qnnGPU` 不受影响 | `Tests/JetlinkServerTests/OrtBackendTests.swift` |
| 文档：`docs/qnn-htp-stubs.md` 两段（path 与 type 互斥；报告打印 domain） | `docs/` |

## 3. 新 APK（本轮唯一要装的）

```
http://192.168.10.79:8012/cn-911685d-pairdiag/app-release-pairdiag.apk
112,669,522 B   sha256 604efa84567fcb7f4166dcdc394c20bed2316fb46fff53b52cc4f2da8984cc1b
```
- 与在装的证书同（`043da762…`，v3）⇒ **覆盖安装**。
- 内含：CI `cn-911685d` 的 `libjetlink.so`（`dc7a9e64f8ae2062…`，本轮修复在内）＋
  匹配的 QAIRT 2.51.40 五件套（Skel 仍为 SDK 原件 `b06247fa…`）。
- CI 备注：run `38735813429` 的 macOS「Swift build and tests」挂在一个无关的 flaky
  用例（`PageAuthTests` 第 6 次期望 429 得到 401）；`cn-prerelease` 只依赖
  `android`/`app` 两个 job，所以 release 照常产出（该 job 全绿）。

## 4. 拿到新日志先看这四段

1. `the runtime's own lines, as onnxruntime and QNN wrote them:` ← QNN 这次真的被问了，
   第一句就是它的话（device create / interface / unsupported op / Skel 被拒）。
2. `this app's SELinux domain, as the kernel reads it:`
3. `opened by path before the session, so every name finds these:` ← 四个 `(would not
   open)` 出现，则 phone-own 路在本机到此为止。
4. `the pair this run is set to use, and the phone's own`

## 5. 仍卡着的、和下一步

- **方案A（真证据）现在有条件做**：comma 上 `adb` 1.0.41 / 34.0.4 就绪，但
  `adb devices` 为空 —— 手机没以 adb 设备出现（Accelerator Link 与 ADB 共用 USB 口，
  CHANGELOG: “Turning on the Accelerator Link turns ADB off”）。可行的是**无线调试**
  （Android 11+，comma 上 `adb pair`）。三条命令：

  ```bash
  adb shell ls -lZ /odm/lib/rfsa/adsp /odm/lib64            # 标签与可见性
  adb shell getprop | grep -iE 'fastrpc|npu|qnn|dsp'        # 策略属性
  adb logcat -d -s jetlink -s adsprpc -s libc | tail -200   # avc / open_shell / work control
  ```
  更强的做法：`adb push` QAIRT 的 `qnn-net-run`+V85 pair 到 /data/local/tmp，以 **shell
  用户**跑一次 —— 成功=只是 app 域被拒（要有特权进程）；失败=整机策略（等厂商/系统 app）。

- 若 H1 成立（第三方 app 一律被拒）：APK 侧无解。出路是系统/厂商签名 app、或厂机自带的
  加速栈（NNAPI 的 `libnspextensiongenericqnnservice.so` 就在机器上；Play 服务的 LLM
  Inference / LiteRT-NPU Qualcomm dispatch）。
- **大模型**：同一条 FastRPC 通道、同一堵墙 —— 现在 NPU 上不了；phone **GPU profile**
  继续可用（本轮结论不变）。
