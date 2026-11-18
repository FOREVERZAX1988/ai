# 11-17 下午到晚上「临时故障 → 关开 ACC → 转向系统未对准」根因分析与修复

日期：2026-11-18（用户睡前委托，自主完成）
涉及 routes：11-17 15:00–20:30，route `00000029/2b/2d/31`（跑 db1ffd9ea 与 67852cd25 两版，**两版都有**，非版本回归）

## 1. 现象（用户描述 → 代码事件映射）
- 「临时故障」= `locationdTemporaryError` / `paramsdTemporaryError`（selfdriveState.alertText1 显示 "X Temporary Error"）
- 「转向系统未对准」= `Steering misalignment detected`（`events.py:222 paramsd_invalid_alert()`，第二行 "Angle offset too high (Offset: -13.9°)"）

真实时间线（rlog/qlog 逐段扫描，铁证）：
```
16:12 seg0  commIssue + locationdTemporaryError + steerUnavailable（临时故障出现）
16:13-16:19 locationdTemporaryError 持续 7 段
16:16-16:30 paramsdTemporaryError 开始并持续 14 段
16:30 seg18 "Angle offset too high (-13.9°), Steering misalignment detected" ← 转向未对准
20:06-20:13 同样序列（route 31），20:28 "Angle offset -11.5° 转向未对准"
```
关开 ACC 只是让 `paramsd_invalid_alert` 在下一次进入时重新评估并弹出——**不是 ACC 开关本身导致的**。

## 2. 根本原因（两层因果）

### 层1：locationd 误判 inputsOK=False（"临时故障"的来源）
`locationd.cc:806`: `inputsOK = sm.allValid() && are_inputs_ok()`
`are_inputs_ok()` → `critical_services_valid(observation_values_invalid)`，其中陀螺仪交叉校验：
```cpp
// locationd.cc:278-286
float err = abs((meas[2] - gyro_bias[2]) - camodo_yawrate[0]);
float threshold = 30 * camodo_yawrate_distribution[1];   // camodo std ~0.001 → 阈值 ~0.03 rad/s
bool gyro_valid = err < threshold;
if (valid) counter *= 0.9993; else counter += 1.0;        // INPUT_INVALID_THRESHOLD=0.5
```
- Macan 上相机 odometry 的 rotStd ≈ 0.001 rad → 阈值仅 **0.03 rad/s**
- 实测 seg4 陀螺仪偏差中位数 0.0085、p90 0.028、p99 0.067、峰值 0.103 rad/s（seg8 正常时中位数仅 0.0007）
- **7.8% 的陀螺仪帧超阈值**，counter 累积到 236（阈值 0.5）→ inputsOK=False 整段
- Python 用真实 rlog 数据复现：seg4 invalid=491/6289(7.8%)、counter_peak=236；seg8 invalid=4(0.1%)——与实测 inputsOK（seg4 100% False / seg8 100% True）吻合

### 层2：paramsd 用被否定的数据学习 → angleOffset 跑飞锁死（"转向未对准"的直接原因）
设备数据（seg4 全程）：`inputsOK=False`，但 `angularVelocityDevice.valid=True`、`posenetOK=True`、`sensorsOK=True`（1200/1200）。
`paramsd.py:94` 旧代码：
```python
yaw_rate_valid = msg.angularVelocityDevice.valid   # 没有检查 inputsOK！
```
→ paramsd 把 locationd 自己判定不可靠的 yaw rate 当有效观测喂进 KF → angleOffset 从 -1.7° 跑到 -10° 以上（`OFFSET_MAX=10°`，滞回恢复阈值 8°），最终锁在 -13.9°、`angleOffsetValid=False` → 不自愈 → 下次进入弹"转向系统未对准"。

这是明确的逻辑缺陷：**下游消费者必须尊重上游 locationd 的 inputsOK 总判定**，不能只看单个 valid 位。

## 3. 修复（本地 commit f61dc9f2b，未推远端/未装机重启）
1. **根治**（`paramsd.py`）：`yaw_rate_valid` 与 `roll_valid` 都加 `and msg.inputsOK`。输入被上游否定时不采用其 yaw/roll，走 bound 分支（yaw=0、大 std）。回归测试 `test_inputsOK_false_ignores_yaw_rate_and_roll` 已加并通过。
2. **缓解**（`locationd.cc`）：交叉校验阈值加绝对下限 `max(0.05, 30*std)`。防止 camodo std 极小时阈值趋近 0；0.05 远小于真故障（>0.1 rad/s），不影响异常检测。诚实说明：此改动只把误判从 7.8% 降到 2.1%，counter 仍会越界，因此**它缓解但不根治"临时故障"报警**——根治项是 #1。

验证：新单测在设备通过（另一失败 `test_read_saved_params` 是单独跑也失败的预存问题，与本改动无关）；locationd.o 经 scons 增量编译成功（exit 0）。

## 4. 待办 / 给用户明早的决定
- **设备当前没重启**：文件已同步到设备（paramsd.py + locationd.cc + 新编译的 .o），但运行中的 comma 进程仍是旧代码。要让修复生效需完整 build + 重启 comma（车静止时安全）。我未在用户睡觉时擅自重启。
- **未推远程**：主线带 AGNOS 20.6 bump 未与设备对齐（见 MEMORY.md），推送时机由用户决定。
- **locationd 层1 未根治**：临时故障报警可能仍偶发（陀螺仪真实偏差大是 Macan 硬件特性）。若要根治需改 `observation_values_invalid` 计数器机制（invalid +1 / valid ×0.9993 权重失衡），影响面大，建议观察 #1 修复后症状是否消失再决定。
- 复测建议：装机后跑同一段路，看是否还有"转向系统未对准"；若有，再回头处理层1。

---

## 5. 【重要更正】2026-11-18 上午实测：上面的层1归因有误，故障另有一条主因

本文第 2 节把「临时故障」归给 `sunnypilot/selfdrive/locationd/locationd.cc` 的陀螺仪交叉校验。
**这条归因是错的**：该文件编出来的是 `locationd_llk`，它只发布 `liveLocationKalman`，**不发布 `deviceMotion`**。
paramsd 消费的 `deviceMotion` 来自 Python 版 `openpilot/selfdrive/locationd/locationd.py`
（`system/manager/process_config.py:395` 是 `PythonProcess`）。两份实现的 invalid 预算机制完全不同
（C++ 阈值 0.5 / decay 0.9993；Python `INPUT_INVALID_LIMIT` 按频率缩放、gyro 阈值 9.5），
拿 C++ 的常数去解释 Python 的行为，结论不成立。

### 5.1 现场实测（route 00000036，2026-11-18 10:24–10:33）

用户实时复现，全程抓到：

| 时刻 | 事件 | 数值 |
|---|---|---|
| 10:27:53 | `paramsd Temporary Error` / TAKE CONTROL IMMEDIATELY | offset **-10.03°**，`angleOffsetValid=0`，`valid=0` |
| 10:28:35 | `Steering misalignment detected` | offset **-12.21°** |
| 10:29:44 | 倒车入库后告警消失 | offset **-9.02°**（低于 10° 阈值即判 valid） |

`deviceMotion` 全程 `inputsOK=1 posenetOK=1 sensorsOK=1`，locationd 侧 `inv{'gyroscope': 0.0}`。
**`inputsOK` 门控（本文第 3 节 #1）在这个故障模式下不生效**——它不是这个 bug 的原因也不是解药。
它仍然是一个合理的防御（针对「上游确实否定输入」那条独立路径），故保留。

### 5.2 真正的根因：低速把 yaw-rate 误差放大成转角误差

rlog 逐帧 + 用生产 `VehicleParamsLearner` 离线重放（同一份 deviceMotion/carState，轨迹重合到 1° 内）：

```
t=165s v=4.2 steer= 3.8 offset=-3.76   (重放 -3.84)
t=185s v=3.8 steer= 4.5 offset=-7.20   (重放 -7.29)
t=200s v=3.6 steer=-7.5 offset=-10.50  (重放 -10.98)
t=205s v=0.5            offset=-12.21  (重放 -12.80) -> 锁死
```

漂移 **100% 在 `ANGLE_OFFSET_FAST`** 上；慢状态 `ANGLE_OFFSET` 只走 -6.68 → -6.82。

机理：学习器用 `δ ≈ yaw_rate × steerRatio × wheelbase / v` 反推几何。同一个 yaw-rate 误差，
折算成转角误差按 1/v 放大——本车（sr 15.5 × 2.81 m）上 0.01 rad/s 在 **4 m/s 是 6.1°**，
在 25 m/s 只有 **1.0°**。而 `MIN_ACTIVE_SPEED = 1.0` 就开始学，于是泊车/市区工况把放大 4–6 倍的
噪声灌进 `ANGLE_OFFSET_FAST`；该状态过程噪声 0.25°/步、零观测标准差却有 10°（几乎没锚住），
随机游走 8° 后把 total 顶过 `OFFSET_MAX=10°` → `angleOffsetValid=0` 且 `valid=0` → 两条告警同时具备条件。

### 5.3 修复（commit 64171ffd5f）

- `paramsd.py`: `MIN_ACTIVE_SPEED` 1.0 → **6.0**（约 21 km/h）。同一 route 的离线 A/B：
  1.0 → 终值 -12.80°（报警区）；4.0 → -4.99°；6.0 → 无漂移。
- **回退** `locationd.cc` 的阈值下限（改错模块，且只增加上游合并债）。`locationd_llk` 不参与本链路。
- 新增回归 `test_low_speed_does_not_activate_learner`（3 m/s 不激活、8 m/s 激活）。
- 一次性清除 `LiveParametersV2`（旧值 `angleOffsetDeg=-9.023 / average=-7.105` 是历次低速污染的棘轮累积；
  `retrieve_initial_vehicle_params` 只校验 steerRatio，不校验角度偏移，所以坏值会跨行程继承）。

### 5.4 更正「倒车就自己好了」的解释

不是自愈。两层原因：①低于 10° 阈值即判 valid；②重新点火 paramsd 重启后从 Params 里继承
`angleOffsetAverageDeg` 继续起步。这次同时清掉了缓存，下次从 0° 起步（实测直行中位约 0.8°）。
