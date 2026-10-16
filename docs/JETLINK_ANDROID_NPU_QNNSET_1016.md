# Jetlink Android NPU —— H 轮：手机自带那套进仓库，普通编译即 matched（2026-10-16）

> 设备：Snapdragon **SM8975** / ColorOS 17 / OPPO PYB110（一加16）
> 仓库 `FOREVERZAX1988/jetlink` `cn`：`fa48c11` → **`f5fe166`**（本轮两个提交）
> CI：run `38837891307`（`f5fe166`）＝ tag **`0.8.7-1016-5`**
> 前一轮：`ai/docs/JETLINK_ANDROID_NPU_VENDOR_1016.md`（G 轮，2.48.5 手工注入 APK）

## 0. 本轮要回答的两句用户话

1. 「那 5 个文件你现在 comma 机子上没有吗？」→ **有，五个都在**，不用手机、不用 adb（见 §1）。
2. 「我们代码提交上去，上游自己编译出来的 apk 能直接装一加16 上用吗？」→
   **不是「改改就算」：要 (a) 那五个文件进仓库（本轮已做），(b) 上游有 release 签名钥匙
   （上游没有，见 §4）。**

## 1. 五个文件在哪（本机，已与能用的 APK 对过）

10-15 23:24 与 10-16 07:31 两轮 adb pull 就落在本机了，两处副本内容相同：

| 落地 | 说明 |
| --- | --- |
| `/data/media/qnn-v85-v248/` | 本轮用的 staging（五件） |
| `/data/jetlink-artifacts/work/_probe/` | 上一轮 adb pull 的原始落地 |
| `/data/media/qnn-v85/` | 对照：QAIRT 2.51.40 那套（上上轮） |

五件（全部 `v2.48.5.260901221701`）与 `app-release-vendormatched.apk` 里的同名条目
**逐字节相同**（本轮开工时逐条 sha256 核对）：

| 文件 | bytes | sha256 |
| --- | --- | --- |
| `libQnnHtp.so` | 3,778,744 | `1108ace00a71059d8b8bde5e63a3c7e296dcdb33e88d789d5e6cc88200a27d59` |
| `libQnnHtpPrepare.so` | 88,128,192 | `8879389024c43226e6c7b441b55146a9d4fd941f931bc2a7bfbc8626645bc02e` |
| `libQnnSystem.so` | 4,052,904 | `8b2f9dffd181bb4753491e78881573a36d5f3ac1af2ca1f61ca24a4e6f2fd9f8` |
| `libQnnHtpV85Stub.so` | 779,448 | `3064fd029b4d483fc1365304e4f9a0f06215bef2506d4fa8b6fc6c37209e3880` |
| `libQnnHtpV85Skel.so` | 12,582,764 | `1d4abb21e93817924f8cbcc6535b0b12e14d40276983e5b37caa32744034add9` |

## 2. C：让「普通编译」出的 APK 就是能用的那一版

`jetlink` 仓两个提交（`8978429`、`f5fe166`）：

1. **五件进 `android/app/src/main/jniLibs/arm64-v8a/`**（替掉原来那对 2.51 的 V85）。
   `build.gradle.kts` 钉死五个哈希，**半套即编译失败**（QNN 对半套是静默拒绝）。
   `packaging.jniLibs.keepDebugSymbols` 让 AGP 别改写这五个字节。
2. **三件同名库要赢过 AAR**：新增 `onnxRuntimeLibraries` 任务，`src/main/jniLibs` 里有的名字
   就不从 AAR 取；`onnxruntime-android-qnn` 不再当 `implementation`（它只管 libonnxruntime.so，
   真正带 QNN 那批库的是它依赖的 `com.qualcomm.qti:qnn-runtime:2.42.0` AAR —— 第一次改动漏了
   这一点，1016-4 的 APK 里 V68..V81/Gpu/Dsp 全没了，`f5fe166` 用 `onnxRuntimeNative`（传递）
   配置修好）。

## 3. 验证：CI 出的 APK 与「能用的那版」逐字节比

`0.8.7-1016-5/app-release.apk`（110,321,464 B，sha256
`e2c54eec6d64e2dd7a5be8426598d07eca80bace983e51f137cf4a75cc9410ae`）里：

- `lib/arm64-v8a` 共 29 个 `.so`，其中 **16 个 QNN/LiteRT 库与
  `app-release-vendormatched.apk` 逐字节相同**，五个手机自带件全部 **PHONE-MATCH**；
- 与 vendormatched 只差 `libjetlink.so`（新代码）与 3 个 dex/dexopt 条目；
  entry 集合 166 vs 167（差的是 `META-INF/services/*` 的 R8 随机名）。

**结论：C 成立** —— 以后不必再手工注入，CI/任何人从源码编译出来的就是那一版。

手工重签一份可覆盖安装的（CI 出的是 debug 签名，见 §4）：
`/data/jetlink-artifacts/0.8.7-1016-5/app-release-vendorset.apk`
（110,318,352 B，sha256 `6cebd020cf6ee02a4ca9c49aab2db84df91c712ddffb8b031f2396a62933df41`，
证书 `043da762…`；除签名块外与 CI 版逐条目相同）。
局域网：`http://192.168.10.79:8012/0.8.7-1016-5/app-release-vendorset.apk`

## 4. A：上游（mouxangithub）还卡在哪

1. **签名**。本仓 CI 的 `Write the release key` 两步都是 **skipped**（仓里没有
   `ANDROID_KEYSTORE_BASE64`）⇒ cn 的 APK 是 runner 每次现生成的 debug key 签的，
   **装不到手机上**（手机上是 `043da762` 那个 release 签名），要先卸载或重签。
   上游仓更没有我们的钥匙：**他编译出来的 APK 一定装不上**（除非卸载）。要让「他编译的能直接装」，
   得把 keystore 放进上游的 secrets，或继续由我们重签分发。
2. **内容**。`mouxangithub/jetlink` 的 `cn` 现在还是 `9babbef`，**连 V85 那对都没有**
   （手上有他 CI 出的 `upstream-1016-3.apk` 佐证：`libQnnHtpV85*.so` 完全不存在，QNN 只有
   AAR 的 2.42 那批）。我们的提交合过去才会带上五件。
3. **许可与体积**。Qualcomm 的许可只允许这些库随 app 分发；仓库现在多了约 105 MB 二进制
   （`libQnnHtpPrepare.so` 84 MB，GitHub 已报「>50 MB」告警）。上游未必接受把厂商库提交进仓库，
   备选：把五件当 release 资产 + CI 下载步骤，或只在自有仓保留。
4. **副作用**。V68–V81 的 pair 仍是 AAR 的 2.42，配 2.48.5 的 backend 属混装，那些机器可能
   NPU 失效回落 GPU。要不要这样默认，得由上游拍板。

## 5. 待办（等手机回到网内）

- 装 `app-release-vendorset.apk`（**设置里 Phone's Own QNN = OFF**），存 `npu:` 报告三段
  （`buildFacts` / `publicTables` / `mappedPaths`）与 EP context 那几行 —— 上一轮只是用户口报，
  本机没有设备侧日志。
- 性能「还不如 8e5」另开一轮：先要那份 `npu:` 报告与逐帧耗时。
