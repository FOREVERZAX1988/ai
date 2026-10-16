# Jetlink Android NPU —— 10-15 E/F 轮：方向 3+1 出一版，两套 build 都是谁（2026-10-15/16）

> 设备：Snapdragon **SM8975** / ColorOS 17 / OPPO PYB110（一加16）｜仓库 `FOREVERZAX1988/jetlink` `cn` @ `fa48c11`
> 本轮按用户指定顺序落地 **方向 3（报告 adb 才看得见的两件事）** 再 **方向 1
> （`uses-native-library` 让 namespace 够得着 /odm）**，一版 APK 一起出。

## 0. 本轮要装的 APK（唯一一个）

```
http://192.168.10.79:8012/0.8.7-1016-3-pairdiag/app-release-pairdiag.apk
112,698,194 B   sha256 3f6b8744cdc402971c93bbd1be571c93f5c908e989072d69d046ebb8ed9934e5
（备用）https://github.com/FOREVERZAX1988/jetlink/releases/download/0.8.7-1016-3/app-release-pairdiag.apk
```
- CI：run `38821980822`，全绿；release 标签 **`0.8.7-1016-3`**，`libjetlink.so` = `ac43360a3754ddf7`（本轮修复在内）。
- QNN 五件套仍是 **QAIRT 2.51.40.260930**（Skel `b06247fa…`，SDK 原件）。
- 证书 `043da762…`（v3）与在装版本相同 ⇒ **覆盖安装**，不必卸载。

## 1. 方向 3：报告新增三段（对着一加16 的日志读）

| 新段 | 读什么 |
| --- | --- |
| `the QNN builds in question, as the files say of themselves` | 每个库的**版本号**与**有没有 NPU 调度器接口**（`qnn::IScheduler`） |
| `the phone's own QNN, by name, as this namespace answers it` | 四个声明名各自解析到**哪个路径**（/odm 还是 /data/app） |
| `the public library tables, the other half of a declared name` | 手机的 `public.libraries.txt` 里有没有 QNN 名 |

## 2. 实测：两套 build 各自是什么（本地读文件，不靠 adb）

| 库 | 版本 | `IScheduler` |
| --- | --- | --- |
| `/odm/lib64/libQnnHtp.so`（手机自带） | `v2.48.5.260901221701` | **无** |
| `/odm/lib64/libQnnHtpV85Stub.so` | `v2.48.5.260901221701` | **无** |
| `/odm/lib/rfsa/adsp/libQnnHtpV85Skel.so` | `v2.48.5.260901221701` | **无** |
| app 自带（本轮 APK） | `v2.51.40.260930230134` | **有**（`IScheduler` / `NpuSchedulerFactory`） |

两套都是完整的 V85 五件，文件名一样、字节全不同。日志里
`RPC NPU scheduler enforcement enabled` + `opened handle without priority token`
正是**调度器接口这一代**才有的东西 —— 我们拿一对 2.51 去开一台 2.48.5 的机器。
（手机侧文件系 10-15 23:24 由上一次会话 adb pull 到
`/data/jetlink-artifacts/work/_probe/`；本轮不再需要 adb。）

## 3. 方向 1：声明是半个名字

`uses-native-library` 是「namespace 允许看 app 目录之外」的正规口子，本版在
`AndroidManifest.xml` 声明了 QNN 的四个名字；**另一半在手机**：Android 拿
`/system/etc`、`/vendor/etc`、`/odm/etc` 的 `public.libraries.txt` 解析声明，
表里没有的名字，声明也够不到 —— 名字只会落到 app 自己的目录，或者无人应答。
所以 backend 现在**先试绝对路径、再试裸名字**，两次都写进报告。

已于上次 adb 取证知道：`/vendor/etc/public.libraries.txt` 只有
`libadsprpc / libcdsprpc / libsdsprpc`（无 QNN）；`/odm/etc/public.libraries.txt`
**没查过** —— 新报告会打出来。若它列了 QNN，方向 1 本机就能走通；若没有，
本机 phone-own 路到此为止。

## 4. 回答用户的三个问题

1. **是芯片太新、没有 API 吗？** ❌ 不是。V85 整套（backend/Stub/System/Prepare
   + `/odm/lib/rfsa/adsp` 的 Skel）+ NNAPI-QNN 扩展都在机上，厂商服务
   （`libaiboost_qnn_sr.so` / `libarcsoft_qnnhtp.so` / `libnspextensiongenericqnnservice.so`）
   自己在用；缺的不是 API，是**许可**。
2. **要升 QNN 到 2.51 吗？** 我们**已经**是 2.51.40（V85 五件就从
   `v2.51.40.260930` 解出来的）。真正相反：**手机是 2.48.5**，比我们旧一代。
3. **是别的手机行、我们代码不行吗？** 半对：
   - 代码侧确实有两处欠缺，本版补了（够不到 /odm；报告说不出两套 build 是谁）；
   - 但 DSP 拒绝的是 **unsigned PD / `remote_work_control`**（`errno Permission
     denied`），加上这代固件的 **NPU scheduler enforcement**：这是
     **固件/sepolicy 裁决**，改 APK 越不过去。用户已确认「一加15 能用」是记错
     （换回官方版也只有 GPU）。

## 5. 为什么别的没 root 的手机能调 NPU —— 要一条命令才判

同一组命令在能用的机器上跑一次即可判（三处差异任一处成立就够）：

```bash
adb shell 'getenforce; getprop ro.soc.model; cat /proc/self/attr/current'
adb shell 'ls -lnZ /dev/fastrpc-cdsp; (head -c1 /dev/fastrpc-cdsp >/dev/null 2>&1 && echo CDSP_OPEN_OK) || echo CDSP_OPEN_FAIL'
adb shell 'cat /vendor/etc/public.libraries.txt /odm/etc/public.libraries.txt'
adb logcat -d | grep -iE 'remote_work_control|open_shell|avc:.*fastrpc|NPU scheduler'
```
一加16 上已知：`/dev/fastrpc-cdsp` = `crw-rw-r-- 1 1000 1000`（只给
system），连 `adb shell`（uid 2000）都 `CDSP_OPEN_FAIL`。

## 6. 下一步（真正可能解锁的，按代价排序）

1. **一加15 对照**（用户明天给日志）：只判「那台为什么行」，不改代码。
2. **凑一套 vendor build 放进 app 私有目录**（需要 adb 拉 88 MB 的
   `/odm/lib64/libQnnHtpPrepare.so`，其余四件已在本地）：让开 handle 的 URI 也
   变成 `qnn_2_48_5_skel_handle_invoke`，这是唯一没测过的「2.51 对 2.48.5」假设。
3. **走厂商的门**：NNAPI（`libneuralnetworks.so` 在公开库表里）或 Play 的
   LiteRT-NPU Qualcomm dispatch —— 由系统服务代跑，绕开 app 自己的 FastRPC 拒绝。
4. **root**：唯一能改 sepolicy / 换域的办法。

## 7. 大模型与链路

- **NPU**：在这道门被厂商打开（或走 2/3/4）之前，本机起不来；`GPU profile` 仍
  是唯一能跑的（用户已排除）。
- **USB 链路（方案B）**：与 NPU 是两件事，链路只搬帧。comma 侧
  `openpilot.sunnypilot.jetlink_adapter` 在跑、`JetlinkLink=1`、`JetlinkSpec` 已
  指向 404a18cfd…onnx，仓库侧无需再改。注意：**开 Accelerator Link 会关掉 USB 上的
  ADB**（上链协议自己的约定），所以 adb 取证一律走无线调试。
