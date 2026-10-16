# Jetlink Android NPU —— 10-15 续：手机自带那套 V85 在 /odm，开关没走到它的 Skel（2026-10-15）

> 设备：Snapdragon **SM8975**（ColorOS 17 / SDK 37，OPPO PYB110）｜jetlink `cn`
> 起因：装了 `cn-3959349-pairdiag` 后 NPU 仍旧 `took no node of model`（18:38 日志），
> 用户同时问「手机上好像没找到你说的 Phone's Own QNN」。

## 0. 三件事

| 问题 | 结论 |
|------|------|
| 18:38 那份日志**一句话证据都没有** | ❌ 代码 bug：`HostDiagnostics.report()` 里 `claim()` 把 60 秒内的第二次报告**整个吞掉**，只留 `the phone's NPU runtime was read a moment ago, not again for: …`。而一次失败的 NPU 启动**恰好写两份报告**（preparation 一次、随后真正加载又一次），第二份才是用户重试后贴出来的那份。17:36 与 18:38 两次中招 |
| 「Phone's Own QNN」在哪 | **设置 → 关于 → 「版本」连点 7 次**（`DEVELOPER_TAPS`，弹出「开发者设置已开启」）→ 设置页出现**「开发者」**段，在「检查更新」之上 → 里面是**「使用手机自带 QNN」**。隐藏是刻意的，和 Android 的「内部版本号」一样 |
| 手机到底有没有自带 QNN | ✅ **有，而且是完整一套 V85**，在 **`/odm`**：`/odm/lib64` 放 backend/Prepare/System/Stub，**`/odm/lib/rfsa/adsp` 放 Skel**。10-14 那篇写「手机没自带 QNN」是因为只查了 `/vendor/lib64` |

## 1. 手机自带那套（16:34 报告里 2026-10-10 13:44 落盘的那批）

| 文件 | 字节 | 目录 |
|------|------|------|
| `libQnnHtp.so` | 3,778,744 | `/odm/lib64` |
| `libQnnHtpPrepare.so` | 88,128,192 | `/odm/lib64` |
| `libQnnHtpV85Stub.so` | 779,448 | `/odm/lib64` |
| `libQnnSystem.so` | 4,052,904 | `/odm/lib64` |
| `libQnnHtpV85Skel.so` | 12,582,764 | `/odm/lib/rfsa/adsp` |

对照 APK 自带那套（QAIRT 2.51.40）：4,158,272 / 88,234,712 / 875,568 / 4,125,232 / 14,058,420。
两套**五个文件名一模一样、字节全不同** —— 这正是「跨版本混用」最难查的形态。

## 2. 开关为什么没救回来：两个缺口

1. **backend 找到了**：`Bridge.qnnBackend()` 搜 `/vendor/lib64` → `/system/lib64` → `/odm/lib64`，这台机器命中 `/odm/lib64`，所以开启后 QNN 后端确实换成手机自带那份。
2. **Skel 没找到**（本轮的实质 bug）：`ADSP_LIBRARY_PATH` 的「系统 DSP 目录」写死为
   `/system/lib/rfsa/adsp;/system/vendor/lib/rfsa/adsp;/dsp`。这台机器上前两个**不存在**、
   第三个**没有 Skel** ⇒ Hexagon 一路 fall through 到 **app 自己的 Skel**，也就是
   「DSP 不肯收」的那一份。**已改为**：补上 `/vendor/lib/rfsa/adsp`、`/vendor/lib/rfsa/cdsp`、
   **`/odm/lib/rfsa/adsp`**。
3. 顺带记一笔仍未解的：QNN 的 `libQnnHtp.so` **按名字 dlopen** 自己的 Stub
   （`libQnnHtpV85Stub.so`），而 app 的 nativeLibraryDir 在 loader 默认搜索路径里 ⇒
   即便 backend 换成 `/odm/lib64` 那份，Stub 仍可能是 app 的（**一个 backend、两种 build**）。
   决定这一点的**唯一一行**是报告里
   `the QNN and onnxruntime libraries this process has open`（读 `/proc/<pid>/maps`，带完整路径）。

## 3. 本轮改了什么（`31abcbc`，CI run 38722832623）

| 改动 | 文件 |
|------|------|
| **报告每次都写**；被扣住的只剩「目录的读取」（每目录 60 秒缓一次），任何理由都不能因为重复而没打印 | `JetlinkServer/HostDiagnostics.swift` |
| 报告里**每一行文件都带它所在的目录**（`/odm/lib64  -rw-r--r-- … libQnnHtp.so`）。三个目录三套 QNN，只给文件名等于没说 —— 用户的「找不到」就是这么来的 | 同上 |
| 「手机自带那套」的搜索目录补上 DSP 侧（`ownDirectories()`：含 `/odm/lib/rfsa/adsp`、`/vendor/lib/rfsa/adsp`、`/vendor/lib/rfsa/cdsp`） | 同上 |
| `ADSP_LIBRARY_PATH` 的系统侧目录补上 `/vendor/lib/rfsa/adsp`、`/vendor/lib/rfsa/cdsp`、`/odm/lib/rfsa/adsp` | `JetlinkAndroid/Bridge.swift` |
| 文档：手机自带 QNN 在 `/odm`、开关位置、报告每次都写 | `docs/qnn-htp-stubs.md`、`docs/troubleshooting.md` |

## 4. 下一次要贴的四段（顺序即优先级）

1. `the runtime's own lines, as onnxruntime and QNN wrote them:` ← 决定性的那句
2. `the QNN and onnxruntime libraries this process has open:` ← **带全路径**，直接回答「app 的 Stub 还是 /odm 的 Stub」
3. `the pair this run is set to use, and the phone's own:` ← 哪套在生效、手机自带那套在哪
4. `where the Skel is looked for, ADSP_LIBRARY_PATH, in order:` ← 编号即搜索顺序

**跑法**：设置 → 关于 → 点「版本」7 次 → 开发者 → 打开「使用手机自带 QNN」→ 重启 NPU profile → 贴日志。
（`cn-3959349` 起，重试之间不必再等一分钟——那正是本轮修掉的 bug。）

## 5. 仍未做

手机侧 `adb`（logcat/dmesg/ls -Z）仍无，所以
**H1「DSP 是否拒收未签名 Skel」** 与 **H2「手机自带那套能否出 context」** 仍只能由报告间接回答；
在 `31abcbc` 的 APK 装上前，NPU 仍是死的，大模型继续走 **GPU profile**。
