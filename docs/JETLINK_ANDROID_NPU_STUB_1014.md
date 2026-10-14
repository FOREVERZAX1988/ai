# Jetlink Android NPU —— SM8975 的 Hexagon Stub 去哪找（2026-10-14）

> 设备：Snapdragon **SM8975**（`Build.SOC_MODEL`；日志里的 `htp-whole-SM8975` / `gpu-SM8975`）｜jetlink 仓库分支 `cn`
> 起因：APK 的 NPU profile 一直停在 preparing。用户问两件事：
> ①「github 上有 SM8975（这一代 Hexagon，v8x）对应的 Stub 吗？我该搜什么关键词？」
> ②「你 apk 代码里不能直接写入拉 logcat / 看 /vendor 里的 libQnnHtpV* 这些指令，让它们出现在日志里吗？」
> ②已落地（jetlink `3a34279` / `c240179`），用户贴回了运行日志；本文是①的答案与证据。

## 0. 结论速览

| 问题 | 结论 |
|------|------|
| GitHub 上能拿到 SM8975 的 Stub 吗 | ❌ **拿不到**。`libQnnHtpV*Stub.so` / `*Skel.so` 是高通专有二进制（Qualcomm AI Stack License，只在 app 之内可再分发）。公开仓里只会有厂商 blob 镜像（前提是该机型已上市、且有人 dump 固件）。**公开分发的 QNN 目前全都止于 V81 ⇒ V85 这一代的 Stub 在公开处不存在**（除非某台 SM8975 机型的固件自带） |
| 公开渠道最新到哪一代 | `com.qualcomm.qti:qnn-runtime` **2.51.0**（Maven Central，`lastUpdated 20261006104318` = 2026-10-06）只带 **V68/V69/V73/V75/V79/V81** 的 Stub+Skel；APK 实际用的 `onnxruntime-android-qnn` 1.29.0 依赖的 QNN 2.42.0 同样止于 V81 |
| SM8975 是哪一代 Hexagon | 在 V81 **之后**。QNN 2.51 自己的二进制里架构名表 = `V68 V69 V73 V75 V79 V81 **V85** V89`，而 SoC 名表已含 `SM8950/SM8975/SM8975H/SM8975L/SM8975P` ⇒ 首选目标文件名 **`libQnnHtpV85Stub.so`**（配 `libQnnHtpV85Skel.so`）；V85 还是 V89 需 SDK 侧确认 |
| 这台手机自带 QNN 吗 | ❌ 没有。`/vendor/lib64` 只有 `libQnnGpu.so` / `libQnnSystem.so` / `libadsprpc.so` / `libcdsprpc.so`，**没有 `libQnnHtp*.so`** ⇒ HTP 后端必须由 APK 自带 |
| 现场症状 | `QNN SetupBackend failed ... QNN_DEVICE_ERROR_INVALID_CONFIG: Invalid config values` → provider 一个节点都不吃（0.6 s 返回）→ 写不出 EP context → 整模型落 CPU |
| 代码侧结论 | NPU build 拿不到节点时应**直接失败**（`c240179`），并在 `npu:` 报告里写出「本 build 带的 HTP 架构」与「手机自己的 QNN/DSP 库」（`3a34279`） |

## 1. 用户贴回的日志（2026-10-14 22:33–22:37，节选）

```
22:34:35.866 WARNING jetlink.ort: onnxruntime wrote no EP context for model in 0.6 s; each load will compile it again
22:34:35.866 WARNING jetlink.ort: the QNN provider took no node of model (it returned in 0.6 s): the model is on the phone's CPU
22:34:36.363 INFO jetlink.npu: the QNN and onnxruntime libraries this process has open: nothing
22:34:36.363 INFO jetlink.npu: no libjetlink.so in this process's maps, so no library directory to name
22:34:36.363 INFO jetlink.npu: the phone's own QNN and onnxruntime libraries:
22:34:36.363 INFO jetlink.npu:   -rw-r--r-- 1 root root   8290056 2026-10-10 12:39 libQnnGpu.so
22:34:36.363 INFO jetlink.npu:   -rw-r--r-- 1 root root   4053176 2026-10-10 12:39 libQnnSystem.so
22:34:36.365 INFO jetlink.npu:   onnxruntime:  [E:onnxruntime:, qnn_execution_provider.cc:1046 GetCapability] QNN SetupBackend failed Failed to create device. Error: QNN_DEVICE_ERROR_INVALID_CONFIG: Invalid config values
22:37:53.503 WARNING jetlink.ort: the artifact's NPU session holds the model, not a compiled context: this load compiles it for the phone again
```

读法：手机侧没有 HTP 后端；本进程 maps 里连自己的 QNN 库都看不到（AGP 默认 `extractNativeLibs=false`，库在 APK 里，
maps 只映射 `base.apk`，所以旧版诊断的「no libjetlink.so in this process's maps」出现过）⇒ `c240179` 改成从 APK 里 `unzip -l` 读，
并打印它带的架构。

## 2. 证据（本机 + 公开源实测，2026-10-14）

```bash
# 1) 公开渠道最新版本
curl -s https://repo1.maven.org/maven2/com/qualcomm/qti/qnn-runtime/maven-metadata.xml
#   <latest>2.51.0</latest>  <lastUpdated>20261006104318</lastUpdated>

# 2) 2.51.0 这个 aar 到底带了哪些 HTP 库
python3 -c "import zipfile;print([n for n in zipfile.ZipFile('/tmp/qnn-runtime-2.51.0.aar').namelist() if n.endswith('.so')])"
#   jni/arm64-v8a/libQnnHtpV{68,69,73,75,79,81}{Stub,Skel}.so
#   + libQnnHtp.so / libQnnHtpPrepare.so / libQnnSystem.so / libQnnGpu.so / libQnnDsp{,V66Stub,V66Skel}.so
#   （2.42.0 的 aar 同样止于 V81）

# 3) QNN 自己知道到哪一代
grep -a -o -E "V68.{0,50}V89" libQnnHtpV81Skel.so      # V68 V69 V73 V75 V79 V81 V85 V89
grep -a -o -E "SM[0-9]{4}[A-Za-z]{0,2}" libQnnHtpV81Skel.so | sort -u | tail -12
#   SM8845P SM8847 SM8847P SM8850 SM8850L SM8850P SM8950 SM8950P SM8975 SM8975H SM8975L SM8975P

# 4) 高通官方「Supported Snapdragon devices」表（QAIRT 文档 80-63442-10）
#    SPA 页抓不到正文，但其 markdown 源可直接取：
curl -s "https://docs.qualcomm.com/bundle/publicresource/80-63442-10/topics/QNN_general_overview.md"
#   SD 8 Elite Gen 5 (SM8850) | aarch64-android | SOC Model 87 | Hexagon Arch V81 | LPAI v6
#   SD 8 Elite (SM8750) | 69 | V79 ；SD 8 Gen 3 (SM8650) | 57 | V75 ；… 表中没有任何 SM89xx
```

要点：官方**设备表**还没写 SM89xx，但厂商二进制里**架构名表**已经写了 V85/V89、SoC 名表已经写了 SM8975 —— 
即 QNN 2.51 认识这个名字，却不提供它的 Stub/Skel。

## 3. 搜关键词（GitHub code search / 通用引擎都行）

- **文件级（最准）**：`libQnnHtpV85Stub.so`、`libQnnHtpV85Skel.so`、`libQnnHtpV83Stub.so`、`libQnnHtp.so`、`libQnnHtpPrepare.so`、`libSnpeHtpV**Skel.so`（老 SNPE 的叫法）
- **符号 / 配置级**：`QnnHtpDevice_Arch_t`、`QNN_HTP_DEVICE_ARCH_V85`、`QnnHtpV85`、`htp_arch`、`soc_model`、`hexagon-v85`、`hexagon v85`
- **包 / 工程级**：`qnn-runtime`、`com.qualcomm.qti:qnn-runtime`、`onnxruntime-android-qnn`、`qnn_execution_provider`、`QAIRT`、`AI Engine Direct`、`qpm-cli`、`qualcomm_qnn_sdk`
- **SoC 级**：`SM8975`、`SM8950`、`SM8850`、`Snapdragon 8 Elite Gen 5`
- **厂商 blob 镜像（灰色）**：`proprietary_vendor_qcom_*`、`TheMuppets`、`AndroidDumps`、`dumps SM8975`、`vendor/qcom/proprietary`

## 4. 真能拿到 Stub 的三条路

1. **QNN/QAIRT SDK（正路）**：Qualcomm Package Manager（`softwarecenter.qualcomm.com`，免费账号）→ 包名 `qualcomm_qnn_sdk`；
   解开后看 `$QNN_SDK_ROOT/lib/aarch64-android/libQnnHtpV85Stub.so` 与 `lib/hexagon-v85/unsigned/libQnnHtpV85Skel.so`。
   **注意**：SDK 与 Maven 那个裁剪版不同步 —— 「Maven 到 V81」**不等于**「SDK 里没有 V85」，必须自己列目录确认。
2. **手机固件**：`/vendor/lib64/libQnnHtp*.so`、`/vendor/lib/rfsa/adsp/libQnnHtpV**Skel.so`（本机没有 ⇒ 此路不通）。
3. **厂商 blob 镜像**（灰色，见 §3 关键词）：只在该机型已上市、且有人 dump 的前提下才有。

## 5. 坑

- **光有 Stub 不够**：`libQnnHtp.so` 是按 arch **拼文件名 dlopen** 的（所以 `grep -a libQnnHtpV81Stub libQnnHtp.so` 什么也搜不到），Stub / Skel / `libQnnHtp.so` 最好来自同一次 SDK build。
- **Skel 要被 CDSP 接受**（unsigned PD）；`Bridge.swift` 已把 app 的 `native_library_dir` 塞进 `ADSP_LIBRARY_PATH`。
- **别指望「一次编译到处跑」**：多 SoC 的 FCB（`soc_model` / `htp_arch` 传逗号列表）只在 **x86_64 host 离线**准备，且仍受「runtime 是否带对应 Stub」限制。
- **`soc_model` 只认「少数知名芯片」的名字串**，其余要用数字 ID（官方表里 SM8850=87 / SM8750=69 / SM8650=57）；给错不如不给。

## 6. 下一步

1. 找/等带 **V85** 的 QNN runtime：一旦有，把 `libQnnHtpV85{Stub,Skel}.so` 放进 `android/app/src/main/jniLibs/arm64-v8a/`（或 bump `android/gradle/libs.versions.toml` 的 `qnn-runtime` 版本）重出 APK 即可，server 侧代码不用动。
2. 在此之前用 **GPU** profile（LiteRT 或 QNN GPU 都行）跑大模型；NPU profile 会按 `c240179` 直接失败并说明原因，不会再假装 warm-up。
3. 复验方式：装新 APK 后看 `npu:` 段 —— 会打出 `the HTP architectures this build carries: V68 V69 V73 V75 V79 V81`，与手机的 SM8975 对不上即坐实「缺这一代的 Stub」。

---

*整理：2026-10-14｜证据：maven-metadata.xml（2.51.0 / 20261006）、qnn-runtime 2.42.0+2.51.0 aar 列表、`libQnnHtpV81Skel.so`/`libQnnHtp.so` 字符串、QAIRT 文档 80-63442-10 markdown 源、设备侧 `npu:` 日志（用户贴回）*

## 7. 落地（2026-10-15）：这一代的 Stub 进了 fork 的 APK

用户把 QAIRT **2.51.40.260930** 整包（7 GB）放到 `/data/media/`，`find … -iname '*V85*'` 确认
里面确实有 V85 这一代（同一目录还有 `libQnnHtpV85.so`（14.5 MB，PD 版）与
`libQnnHtpV85CalculatorStub.so` 等，未取 —— 取的是 build 文件按名引用的那一对）：

| 文件 | SDK 内路径 | `file` | 字节 | SHA-256 |
|------|-----------|--------|------|---------|
| `libQnnHtpV85Stub.so` | `lib/aarch64-android/` | ARM aarch64，已 stripped | 875,568 | `8c3636f34ff763d872623172e192b64983e0578d124e5b73f064c28e372f3874` |
| `libQnnHtpV85Skel.so` | `lib/hexagon-v85/unsigned/` | QUALCOMM DSP6，32-bit | 14,058,420 | `b06247fa38ffad5b8c55a83ff7d4b5500a69282944c0942253fb57b38eaf6b40` |

按 §6.1 的最小集（只这两个文件，14 MB）：

- jetlink fork（`cn`，commit `204f17c`）新增
  `android/app/src/main/jniLibs/arm64-v8a/libQnnHtpV85{Stub,Skel}.so`。AGP 默认 jniLibs 源集
  ⇒ 进 APK 的 `lib/arm64-v8a/`；`useLegacyPackaging = true`（本来就有）把它们解到
  `nativeLibraryDir`，`libQnnHtp.so` 按名 dlopen Stub，CDSP 从同一目录（`ADSP_LIBRARY_PATH`）取 Skel。
- `android/app/build.gradle.kts` 加守卫：这对文件要么 0 个（上游 / 只有 Maven 的 checkout 照常构建，
  仍止于 V81），要么 2 个；只放一半直接构建失败 —— QNN 对"半套"是静默拒绝（§5）。
- 文档侧：`docs/qnn-htp-stubs.md` 末节改为「The V85 pair this fork carries」（含上表哈希与
  §8 的版本坑），`android/README.md` 的对应段同步。
- **只推自有 fork**：`FOREVERZAX1988/jetlink` 的 `cn`（`13a2e39..204f17c`），
  上游 `mouxangithub/jetlink` 不带这对二进制（Qualcomm AI Stack License 只能在 app 内分发）。

复验（验收标准）：装新 APK 后 `npu:` 段应打出
`the HTP architectures this build carries: … V79 V81 V85`，且 NPU build 能拿到节点
（不再 0.6 s 空手而归、整模型落 CPU）。

## 8. 还没排除的坑：Stub / Skel / HTP 后端库必须同一 build

这对是 **2.51.40**，而 APK 里 `libQnnHtp.so` / `libQnnHtpPrepare.so` 来自
`onnxruntime-android-qnn` **1.29.0** 依赖的 `qnn-runtime` **2.42.0**
（已从 Maven POM 核实：`<artifactId>qnn-runtime</artifactId><version>2.42.0</version>`）。
QNN 要 Stub / Skel / HTP 库同一 build。若装上仍拿不到节点，下一步不是"再找文件"，
而是把同一个 QAIRT build 的 `libQnnHtp.so`（4.2 MB）、`libQnnHtpPrepare.so`（88 MB）、
`libQnnSystem.so`（4.1 MB）一起放进 jniLibs 让三件套同版本（代价是 APK 再大 ~96 MB）。
到那一步时，`npu:` 与 onnxruntime 的 QNN 报错行会写明是哪一侧版本对不上。

> 磁盘：`/data` 已 99%（剩 ~0.5 GB）。QAIRT 整包 7 GB 已删，只留这对文件于
> `/data/media/qnn-v85/`；若真要试 §8 的三件套，得重新取 SDK（同一个包名/URL）。

---

*追加：2026-10-15｜证据：QAIRT 2.51.40.260930 目录清单与 `file`/`sha256sum`、
Maven `onnxruntime-android-qnn-1.29.0.pom`、jetlink `204f17c`。*

## 9. 卡点：这条推送没有 CI（GitHub Actions 对本仓被禁用）

- 推 `cn`（`204f17c`）后**没有产生任何 CI run**：`/actions/runs` 最新仍是 `13a2e397`（16:24Z）。
- `POST …/actions/workflows/ci.yml/dispatches` → `422 {"message":"Actions has been disabled for
  this repository."}`；同一错误在 `release.yml` 上也复现。
- 不是 YAML/触发条件问题：`on.push.branches: ["**"]` 正常，另推一条新分支
  `probe-actions-1015`（同一 commit，已删）同样**零 run**。
- 账号侧也停在同一时段：openpilot 最新 run `2026-10-14T06:16Z`、ai `2026-08-19`、opendbc `2026-07-30`。
  而 `GET …/actions/permissions` 仍返回 `enabled: true`（设置项看着是开的）⇒ 偏向平台侧禁用/额度限制。
- 后果：**`cn-204f17c` 没有 APK 产物**；能装的最新 APK 仍是 `cn-13a2e39`（**不含 V85 对 ⇒ NPU 仍会失败**）。
- 用户侧待查：GitHub → **Settings → Billing**（Actions 分钟 / spending limit）与
  repo **Settings → Actions → General**；恢复后重推 `cn`（或手动 dispatch）即出 APK。
