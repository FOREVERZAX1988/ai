# Jetlink Android NPU —— 10-15：报告读不到事实，诊断就无从谈起（2026-10-15）

> 设备：Snapdragon **SM8975** 手机（jetlink `cn` 分支）
> 起因：用户装了 `cn-204f17c` 的 `app-release-v85matched.apk`（五件 QNN 库统一
> 2.51.40 + 那对 V85），NPU 仍然 `took no node of model`，贴回 13:34 的日志问
> 「问题出在哪里」，并同意「把要确认的指令做进 APK、运行时写日志，我直接贴日志」。

## 0. 结论速览

| 问题 | 结论 |
|------|------|
| 日志里 `the QNN and onnxruntime libraries this process has open: nothing` | ❌ **假阴性**。探针命令是 pipeline：`grep … /proc/<pid>/maps \| grep -oE … \| sort -u`，而 `shell()` 把 `2>&1` 加在整条命令末尾，只重定向了**最后一条**的 stderr；第一条 grep 读不了 maps 时的错误落进 shell 自己的 stderr（无人读）→ 输出为空 → 被写成「nothing」 |
| `the HTP architectures this build carries: none named` | ❌ **假阴性**（同一份日志里 APK 明明带着 V85）。探针第三选择是 `ls -d /data/app/*/*jetlink*/lib/arm64 2>/dev/null`：app 无法 list `/data/app`（0711，可穿过不可读目录）→ glob 展开为空 → 字面量交给 `ls` → 报错行被 `listing()` 当成目录内容打印（日志里 `ls: ls: /data/app/*/*jetlink*/lib/arm64: …` 正是这个双重前缀）；Android 也没有 `unzip` 给「读 APK 条目」那条兜底 |
| 日志里 `the phone's own QNN and onnxruntime libraries` 那批（3,778,744 / 88,128,192 / 4,052,904 / 779,448 / 12,582,764） | ⚠️ **不是这个 APK 的库**：APK 里是 4,158,272 / 88,234,712 / 4,125,232 / 875,568 / 14,058,420，`/data/media/qnn-v85` 又是同一套。也就是说手机上有**第三份 QNN**（日志里 2026-10-10 13:44 落盘），混用是「took no node」的嫌疑之一；新报告把每个目录连路径一起打印，能一次看清是哪一份 |
| APK 到底带没带那对 V85 | ✅ 带了：`lib/arm64-v8a/libQnnHtpV85Stub.so` 875,568（`8c3636f3…`，与 QAIRT 一致）、`libQnnHtpV85Skel.so` 14,058,420（`092467eb…`，**AGP 处理过的副本**，比 SDK 原件 `b06247fa…` 差 503 字节，尾部签名区被清零） |
| `extractNativeLibs` | ✅ **true**（直接解析 APK 的二进制 AndroidManifest：`android:extractNativeLibs` type=0x12 data=0xffffffff，targetSdk 36）⇒ 库在安装时被解到 `nativeLibraryDir`，Skel 是磁盘上的真文件，`ADSP_LIBRARY_PATH` 指得没错。所以「没有 lib 目录」这条排除 |
| 已落地 | `cn-2ad8f63`（CI run 38700393406 全绿）：探针修好并加哈希/运行时日志；同 release 资产 **`app-release-npudiag.apk`**（同 release 签名，可直接覆盖安装）；五件 QNN 库统一 2.51.40，Skel 换回 SDK 原件 |

## 1. 探针的三处假阴性（代码级）

`JetlinkKit/Sources/JetlinkServer/HostDiagnostics.swift`：

1. `shell()` 只重定向最后一条命令的 stderr → 改成 `popen("( \(command) ) 2>&1", "r")`，
   整组都进捕获，失败必留痕。
2. `appDirectory()` 不再 glob `/data/app`（app 读不了），改为三级：
   进程 maps 里 `libjetlink.so` 的目录 → Kotlin 启动时交给服务器的
   `ApplicationInfo.nativeLibraryDir`（`Bridge.start` 存进
   `HostDiagnostics.nativeDirectory`）→ `pm path` 找到已装 APK 的 `lib/<abi>`。
3. 新增：这个进程的两行 `/proc/<pid>/status` 与 maps 行数（探针读错进程时立刻暴露）、
   五件 QNN 库的 `sha256sum`（手机上的副本不是 APK 的就说得出）、
   `ADSP_LIBRARY_PATH` 逐目录列出 Skel/Stub、
   **`the neural runtime's own lines`**（logcat 里 `onnxruntime`/`QNN`/`adsprpc`/
   `cdsprpc`/`fastrpc` 自己的话，不按 pid 过滤，因为 DSP 与 QNN 的拒绝只在那里），
   并把 QNN session 的 ORT 日志级别从「只要 error」放宽到 INFO
   （`jl_ort.c`，provider 为 QNN 时 severity=1）——「吃不下这个模型」的真正原因
   常在 warning 一级，原来被丢掉。同时把构建失败时那句「本 build 没有这个 Hexagon
   的 stub」的断言改成「证据在上面那几行」。

## 2. 装 `app-release-npudiag.apk` 后看三处

1. `every library the app itself carries` + `the app's own QNN, hashed`：目录必须存在，
   `libQnnHtpV85Stub.so`/`Skel.so` 必须在，哈希应等于 `8c3636f3…`/`b06247fa…`。
   若 Skel 是 `092467eb…` 说明装的还是旧 APK。
2. `where the Skel is looked for, ADSP_LIBRARY_PATH`：第一项应是 app 自己的 lib 目录，
   且里面能列出 Skel。
3. `the neural runtime's own lines`：QNN/adsprpc/cdsprpc 亲口说的那句。若是
   `QNN_DEVICE_ERROR_INVALID_CONFIG` → 仍是 backend/Stub 不配套或手机 HTP 固件不认
   V85 Skel；若是 `Failed to get QNN interface` 一类 → ORT（按 QNN 2.42 编译）与
   libQnnHtp.so 2.51.40 的接口版本对不上，那就要换 ORT 侧或退回同版本 backend。

## 3. 命令与产物

- 新 APK：`github.com/FOREVERZAX1988/jetlink/releases/download/cn-2ad8f63/app-release-npudiag.apk`
  （112,690,199 B，sha256 `71e469a2f8392f62…`，v3 签名，证书与
  `cn-204f17c-v85matched` 相同 ⇒ 直接覆盖安装，不必卸载）
- 本地：`/data/jetlink-artifacts/cn-2ad8f63-v85matched/`（README.txt 记来源与哈希），
  注入脚本 `work/inject_matched.py`，签名用 `work/bt/android-15/apksigner` + `work/jre`。
- 手机侧无法自查（app 读不了 `/data/app`、第三方读不了别的 app 的 `/proc`、无
  `unzip`），所以「事实」只能由 APK 自己打印——这也是这次修探针的原因。
