# Jetlink Android NPU —— 10-15 D 轮：adb 接上了，H1 从「间接」变「直接」（2026-10-15）

> 设备：Snapdragon **SM8975** / ColorOS 17 / OPPO PYB110 / **SELinux Enforcing / 零售版**（`adb root` 被拒）
> 主机：comma（`192.168.10.79`）｜jetlink `cn` @ `911685d`（已装 = `cn-911685d-pairdiag`，`lastUpdate=21:03:42`）
> 起因：手机开放**无线调试**，comma 上 `adb devices` 直接出现 `192.168.10.65:40565 device`
> ⇒ 前几轮「方案 A 没条件跑」的 adb 取证，这一轮做了。

## 0. 一句话结论

**这不只是「第三方未签名 app 被拒」——这台手机的 CDSP 设备节点只给 uid 1000(system)；
连 `adb shell`（uid 2000，`u:r:shell:s0`）都打不开它。** 所以 NPU 上不了大模型的原因
**不在 APK、不在 QNN 版本、不在 stubs**，而在**厂商固件/安全策略**；`cn-911685d-pairdiag`
已经是「能问到的都问到了」的形态，**再换一版 APK 也不会改变 DSP 的裁决**。

## 1. 直接证据（2026-10-15 22:16–22:19，comma → 手机）

| 检查 | 结果 | 读法 |
| --- | --- | --- |
| `id` / `getprop ro.soc.model` | `uid=2000(shell) … context=u:r:shell:s0` / `SM8975` | adb shell 的域 |
| `getenforce` | `Enforcing` | 没有 permissive 的余地 |
| `adb root` | `adbd cannot run as root in production builds` | 零售版，没有特权上下文可借 |
| `ls -ln /dev/fastrpc-cdsp` | `crw-rw-r-- 1 1000 1000 10,306` | **DAC：属主/属组 = system(1000)**；app、shell 都不是 |
| `ls -lZ /dev/fastrpc-cdsp` | `u:object_r:vendor_qdsp_device:s0` | 可 open 的域由 sepolicy 决定 |
| shell 试 open CDSP | **`CDSP_OPEN_FAIL`** | 连 shell 都开不了；日志里 `avc: denied { open } scontext=u:r:shell:s0 tcontext=vendor_qdsp_device permissive=0` |
| `/odm/lib64`（V85 整套） | `libQnnHtp.so 3,778,744`、`libQnnHtpPrepare.so 88,128,192`、`libQnnHtpV85Stub.so 779,448`、`libQnnSystem.so 4,052,904`，标签 `same_process_hal_file` | **手机自带完整厂商 V85 栈** |
| `/odm/lib/rfsa/adsp` | `libQnnHtpV85Skel.so 12,582,764`，`same_process_hal_file` | DSP 侧的 Skel 也在 |
| 厂商自己的 NPU 用户 | `libaiboost_qnn_sr.so`、`libarcsoft_qnnhtp.so`、`libnspextensiongenericqnnservice.so` | **NPU/DSP 对厂商服务是活的** |
| `ro.boot.vendor.qspa.npu / .nsp` | `enabled` / `enabled` | 平台 NPU/NSP 被使能 |
| `/vendor/etc/public.libraries.txt` | 只有 `libadsprpc/libcdsprpc/libsdsprpc`；`/system/etc` 有 `libneuralnetworks.so nopreload` | **app 能 dlopen 的只有 RPC 与 NNAPI**，厂商 `libQnnHtp.so` **不在**公开库表里 |

## 2. 三道门，哪一道挡住了

1. **DAC**：`/dev/fastrpc-cdsp` 0644→属主 `system`，第三方 app 与 shell 都进不去。
2. **SELinux**：Enforcing；`u:r:untrusted_app*` 与 `u:r:shell` 都不许 `open` `vendor_qdsp_device`。
   app 只能由 `adsprpc` 兜底走 `vendor.qti.hardware.dsp` **HAL 服务**（日志里的 `open thru HAL`）。
3. **DSP 固件**：经 HAL 建起的 remote session，`open_shell`(unsigned PD) 与
   `remote_work_control` 都被拒（`errno Permission denied`）；且这代带
   `RPC NPU scheduler enforcement` 而句柄 `without priority token`。

⇒ **1、2 由 sepolicy/设备节点决定，3 由 DSP 固件决定；三者都在手机侧，不在 APK。**

## 3. 为什么「一加15 能、这台不能」（待对照，不是结论）

两台都是 ColorOS 17、都没 root、都是第三方 app。最可能的差别（**明天用同一组命令在 15 上取一次即可判**）：

- 15（上一代芯片，HTP≤V81）的固件**不强制 NPU scheduler token** / **允许 unsigned PD**；或
- 15 的 sepolicy 里 `untrusted_app`→`vendor_qdsp_device` 是**放行**的（本机是 denied）；或
- 15 的 `/dev/fastrpc-*` 权限位对 app 可达。

对照命令（在 15 上原样跑，逐行比）：

```bash
adb shell 'getenforce; getprop ro.soc.model; cat /proc/self/attr/current'
adb shell 'ls -lnZ /dev/fastrpc-cdsp /dev/fastrpc-cdsp-secure'
adb shell '(head -c1 /dev/fastrpc-cdsp >/dev/null 2>&1 && echo CDSP_OPEN_OK) || echo CDSP_OPEN_FAIL'
adb shell 'cat /vendor/etc/public.libraries.txt'
adb shell 'getprop | grep -iE "qspa|fastrpc|npu|nsp"'
adb logcat -d 2>/dev/null | grep -iE 'remote_work_control|open_shell|avc:.*fastrpc|NPU scheduler'
```

## 4. 结论与出路

- **「芯片太新、没 API」不成立**：V85 整套 + NNAPI-QNN 扩展都在机上，厂商自己在用；
  **「只等官方公布」也不完全对**：缺的不是 API 是**许可**。
- **APK 侧**：本机到此为止（再改 APK 不越过门 1/2/3）。
- **唯二在 app 侧还**没测**的合法路径**是**走厂商留下的门**：
  1. **NNAPI**（`libneuralnetworks.so` 在公开库表里；`libnspextensiongenericqnnservice.so`
     是 `system` 里跑的 QNN 服务）——由服务代跑，绕开 app 自己的 FastRPC 拒绝；
  2. Play 的 **LiteRT-NPU / LLM Inference** Qualcomm dispatch（同类，服务化）。
  这两条能不能被第三方 app 调到，**可以先用一条 adb 命令探**（不必出 APK）。
- **大模型**：在这道门被厂商打开（或改走上面两条服务化路径、或 root）之前，
  本机 NPU 跑不了；**GPU profile 仍是唯一能跑的**（用户已排除）。

## 5. 本轮没有改代码

`cn-911685d` 已含前几轮全部修复；本轮只取证据，未产生新 APK
（当前安装版 = `cn-911685d-pairdiag`，sha256 `604efa84567f…`）。
