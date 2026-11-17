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
