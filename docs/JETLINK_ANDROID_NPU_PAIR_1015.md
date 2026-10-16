# Jetlink Android NPU —— 10-15 B 轮：报告先说原因，两套 pair 可切（2026-10-15）

> 设备：Snapdragon **SM8975**（jetlink `cn`）。上轮 `cn-2ad8f63` 的
> `app-release-npudiag.apk` 装后仍 `took no node of model`（16:34 日志），
> 用户拍板「按 B 改诊断、出新 APK，现在做不了方案 A」。

## 0. 16:34 那份日志说明了什么

- 好消息：`the HTP architectures this build carries: V68 V69 V73 V75 V79 V81 V85`
  ——V85 那对确实在 APK 里，`ADSP_LIBRARY_PATH` 第一项就是 app 自己的库目录且列出了
  Stub/Skel。**「缺 V85」这条彻底结束。**
- 坏消息：真相仍没打印出来。`... and 128 more lines of it` —— 报告的 200 行预算被
  前面的 `ls` 段和 `getprop` 吃满，**最后两段（`this process's own log`、运行时
  自己的行）被截掉了**；而 `head/wc/grep: /proc/18454/…: No such file` 说明报告
  用的 pid 当时不是活着的进程（`ProcessInfo.processIdentifier`），于是
  「这个进程开着哪些库」永远为空。
- 另发现一处**打印 bug**：`the app's own QNN, hashed:` 只有四个裸文件名、没有摘要
  ——`sha256sum … | sed 's#.*/##'` 里 `.*/` 把摘要连同路径一起吃掉了。而 AAR 的
  Skel 与 SDK 的 Skel **同为 14,058,420 字节、只差 503 字节**，摘要正是分辨它们的
  唯一一行。

## 1. 这轮改了什么（`cn-3959349`，CI run 38711770432 全绿）

| 改动 | 位置 |
|------|------|
| onnxruntime 的 logger 变成 COrt 里的环形缓冲（`jl_ort_callback` + `jl_log_lines()`），**provider 与 QNN 自己的话被留下**；Android 上不再依赖 stderr | `COrt/jl_ort.c` `include/jl_ort.h` |
| 报告把这段读回来，**放在最前面**；此后每段各有自己的行预算（`section(cap:)`）、总数 320，任何一段都不可能再把别的段挤掉 | `JetlinkServer/HostDiagnostics.swift` |
| pid 用 `getpid()`，并把 `ProcessInfo` 的值和 shell（`/proc/$PPID/stat`）算出的值**并排打印**——空段从此不能当结论看 | 同上 |
| 新增 `the pair this run is set to use, and the phone's own`：backend 路径、app 的 Stub、DSP 会先找到的 Skel（按搜索顺序编号）、以及手机自带同 arch 的三件套（含 CalculatorStub，按大小列出） | 同上 |
| `hashes()` 改成 awk 输出 `16 位摘要 + 文件名`（修掉摘要被吃掉的 bug） | 同上 |
| session 抛错时，把 onnxruntime 的原话并进报告与失败信息（原来只有「没写出 context」） | `JetlinkORT/OrtBackend.swift` |
| **Phone's Own QNN**（设置 → 开发者）：ADSP 顺序改为「系统 DSP 目录在前」，并用 ORT 的 `backend_path` 加载手机自带 `libQnnHtp.so`（`/vendor/lib64` → `/system/lib64` → `/odm/lib64`）。默认关＝一切照旧（V68–V81 不受影响） | `JetlinkAndroid/Bridge.swift`、`Settings.kt`、`SettingsController`、`SettingsScreen.kt`、`strings.xml`×2 |

文档：`docs/qnn-htp-stubs.md` 新增「Which pair is in force, in the log」；
`docs/troubleshooting.md` 的 npu 段改为「原因在前」。

## 2. 新 APK

`github.com/FOREVERZAX1988/jetlink/releases/download/cn-3959349/app-release-pairdiag.apk`
（112,669,522 B，sha256 `2f7136474bdcdbbec118863f188a4a52d4eb74add655696913713926afcfdfe1`，
v3 签名、证书 `043da762…` 与在装的那份相同 ⇒ **覆盖安装，不用卸载**；
`BUILD_TAG=cn-3959349` 是最新 release tag，updater 不会误报有新版）。
五件 QNN 库＝上一轮那套 QAIRT 2.51.40（backend/Prepare/System + V85 对，Skel 为 SDK
原件 `b06247fa…`）。

## 3. 下一次贴日志时看这四段（顺序即优先级）

1. `the runtime's own lines, as onnxruntime and QNN wrote them:` ← **决定性的那句**
   - `QNN_DEVICE_ERROR_INVALID_CONFIG` / device create failed → 设备/后端/Stub 层
   - `Failed to get QNN interface` → ORT 与 libQnnHtp.so 接口版本不匹配
   - `unsupported op` / `conversion failed` / `cannot convert` → **图本身**（那就是
     模型/prepare 的问题，与 pair 无关）
   - Skel 加载/签名被拒 → DSP 侧
2. `this process:` —— 三种 pid 读法必须一致，否则下面的空段都是探针的错
3. `the app's own QNN, hashed:` —— 摘要应是 `aaaf6f96…/199371bf…/8c3636f3…/b06247fa…`
4. `the pair this run is set to use, and the phone's own` —— 首次真正写明「哪套在生效」；
   若在设置里打开 Phone's Own QNN 再跑一次，可对比两套 pair 的失败方式（同一份 APK）

## 4. 仍未做

方案 A（adb logcat/dmesg/ls -Z 三条命令）没条件跑，所以「DSP 是否拒绝未签名 Skel」
（H1）与「手机自带那套能否出 context」（H2）仍只能由报告间接回答；NPU 仍是死的，
大模型继续走 **GPU profile**。
