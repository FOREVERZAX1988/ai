# Jetlink Android NPU —— 10-15 第三轮：19:07 报告的两个自伤，与「手机自带那套」为什么只是换了个 backend（2026-10-15）

> 设备：Snapdragon **SM8975**（ColorOS 17 / SDK 37，OPPO PYB110，`ro.soc.model=SM8975`，HTP V85）｜jetlink `cn`
> 起因：装了 `cn-31abcbc-pairdiag`（18:59 出，含 `/odm` 的 ADSP 目录）后 NPU 仍 `took no node of
> model`，用户贴回 19:07 的四段（runtime 自己的行 / 本进程开着的库 / 本轮的 pair + 手机自带的 /
> ADSP_LIBRARY_PATH 逐目录）。

## 0. 19:07 那份日志能读出什么、读不出什么

| 段落 | 事实 | 判定 |
|------|------|------|
| 1. runtime 自己的行 | 只有 onnxruntime 的 `GraphTransformer … modified: 0/1` 与 60 行 `Removing NodeArg 'Transpose_token_*'`，**没有一行 QNN 自己的话**，且被 `... and 40 more` 截断 | ❌ **决定性的一句被 cap 掉了**。QNN 在 **graph transformer 之后**（partitioning 时才建 device）才写拒绝原因，24 行的 cap 正好只留下 transformer、切掉原因 |
| 2. 本进程开着的库 | `grep: /proc/29436/maps: No such file or directory`，整段空 | ❌ **假阴性（第二轮修过又复发）**：探针是 shell 里的 `grep /proc/<pid>/maps`，pid 与 `/proc/self` 不是同一个问题。而同一份日志的「this process's own log, its pid's lines」能按 pid 29436 过滤出 adsprpc 行 ⇒ pid 本身没错，是**跨进程读 maps** 读不到 |
| 3. 本轮的 pair | `the QNN backend this run loads: the app's own libQnnHtp.so, beside the app` | ✅ 读出**开关是关的**：19:07 这次跑的是 app 自带那套，**手机自带（`/odm`）那套从未上过场** |
| 3. 本轮 pair | `no directory in ADSP_LIBRARY_PATH holds a Skel: the DSP has none to load` | ❌ **自相矛盾**：同一份日志第 4 段第 6 项 `/odm/lib/rfsa/adsp: 16940 / 12582764 / …` 里就有 `libQnnHtpV85Skel.so`（12,582,764 B），第 1 项 app 自己那目录里也有 Skel |
| 4. ADSP_LIBRARY_PATH | 7 项，顺序：app 目录 → /system/lib/rfsa/adsp → /system/vendor/… → /vendor/… → /vendor/lib/rfsa/cdsp → **/odm/lib/rfsa/adsp** → /dsp | ✅ 31abcbc 的改动生效了（`/vendor`、`/odm` 三处已补上）；但 **app 目录仍在第 1 位** ⇒ 开关关着时 DSP 先拿到的是 app 那份 **未签名** Skel |

## 1. 那两个「自伤」的代码级原因（都已修）

1. **名字没了**：`HostDiagnostics.named()` 用
   `ls -l <dir> | grep -iE 'skel|stub' | awk '{print $5, $9}'` 取「大小 + 文件名」，
   而这台手机的 `ls -l` 里日期是**两段**（`2026-10-10 13:44`）⇒ 文件名是**第 8 段**，
   `$9` 永远为空 ⇒ 每行只剩大小（日志里正是 `2426448 / 322104 / …`），
   而「哪个目录的 Skel 会被 DSP 先用」是靠**名字**匹配的 ⇒ 每一项都匹配不上 ⇒ 打出
   「no directory … holds a Skel」。**改为 `$NF`**（日期几段都不影响），
   并在选中的那行后面补一句它是谁的 Skel（app 自己那份会额外写明「未签名、DSP 可能不收」）。
2. **`/proc/<pid>/maps` 换成 `/proc/self/maps`**：在同一进程里用 Foundation 读，
   shell 版降为兜底。这条线是唯一能区分
   「app 的 Stub（875,568）还是 `/odm` 的 Stub（779,448）」的证据，也是「一套 pair 还是两套 build」的证据。
3. **runtime 段不再设 cap**（原 24 行）：QNN 的拒绝在 transformer 之后，cap 恰好切在原因之前。
   `lineLimit = 320` 仍在，但不再有哪一段能切掉原因。

## 2. 「手机自带那套」为什么只换了 backend（本轮的第二处改动）

`backend_path` 只让 onnxruntime 去 `dlopen` 手机自带的 **`libQnnHtp.so`**；
而 `libQnnHtp.so` 自己按**名字**去开它的 **Stub**（`libQnnHtpV85Stub.so`），QNN 还按名字开
**Prepare / System**。名字解析的第一条搜索路径就是 **app 自己的 native 库目录** ⇒
「手机自带的 pair」实际是：**`/odm` 的 backend + app 的 Stub + DSP 拿到 `/odm` 的 Skel`**，
**三套 build**，而 QNN 对三套 build 是静默拒绝（一个节点都不吃）。

本轮起，开关打开时 app 会**先把手机自带那几件按绝对路径 `dlopen`（`RTLD_GLOBAL`）**：
`/odm/lib64/libQnnHtp*Stub.so`、`libQnnHtp*Prepare.so`、`libQnnSystem.so`
（`Host.phoneLibraries`），于是之后任何**按名字**的开都会命中已经装好的这几件 ⇒
backend / Stub / Skel **同一套 vendor build**。报告里新增两行：开关的 on/off、
以及「opened by path before the session」实际开了哪几个路径。

## 3. 新 APK（`cn-14bbcb4`）

- CI：run **38726960785**（`cn` @ `14bbcb4`），`libjetlink.so` 与 Android app 全绿；
  产物 = release `cn-14bbcb4` 的 `app-release.apk`，
  再由 `work/build_pairdiag.sh cn-14bbcb4 …` 换成**同一套 QAIRT 2.51.40** 的五件库并 v3 重签 ⇒
  `app-release-pairdiag.apk`（覆盖安装，不必卸载）。
- 与 `cn-31abcbc` 的差别只在四件事：Skell 名字回来了、maps 在自己进程里读、
  runtime 段不截断、**手机自带那套变成一套 build**。

## 4. 下一次怎么跑、看哪几行

**两种情况各跑一次**（设置 → 关于 → 「版本」连点 7 次 → 开发者 → 「使用手机自带 QNN」）：

1. **开关关**：预期仍是 app 那套（V68–V81 的 AAR + V85 对是 2.51.40，未签名 Skel）——
   这一跑用来拿**第一段里 QNN 自己的那句话**（这轮不再被截断），它才是「为什么不吃节点」。
2. **开关开**：`/odm` 的 backend + `/odm` 的 Stub + `/odm` 的 Skel，**一套 vendor build**。
   这一跑是**真正第一次**试「DSP 只收它自己签名的那份 Skel」这个假设（H1/H2）。

要读的三行（按优先级）：
- `the runtime's own lines, as onnxruntime and QNN wrote them:` ← QNN 的原话
  （`QNN_DEVICE_ERROR_INVALID_CONFIG` / `Failed to create device` / skel 加载失败 / unsupported op …）
- `the QNN and onnxruntime libraries this process has open:` ← 现在会带全路径，直接回答
  「app 的 Stub 还是 `/odm` 的 Stub」
- `the pair this run is set to use, and the phone's own:` ← 开关状态 + 被 `dlopen` 的那几个绝对路径 +
  DSP 会先拿到的 Skel 是哪一份

## 5. 仍未做

手机侧 `adb`（logcat / dmesg / `ls -Z`）仍没有，所以「DSP 拒收未签名 Skel」与
「厂商签名那套能否出 context」仍只能由报告间接回答；在这轮 APK 装上前，
NPU 依旧不起作用，大模型继续走 **GPU profile**。
