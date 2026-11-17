# 20:00–20:30 出 bug 路试（route 00000031--b7b6c905ad）诊断回放复现与根因分析

日期：2026-11-18
路线：11-17 20:03–20:30，route `00000031--b7b6c905ad`，共 28 段（seg0–seg27）
设备版本：67852cd25（zp-macanlong-1109），与本地主线 selfdrived.py/safety_guards.py **完全一致**

## 1. 用诊断回放复现的结论

用 `diag_replay.sh` 回放 seg-21（20:24:25，正是 commIssue 段），camera-less 模式：

**成功复现的警告：**
- `sunnypilot Unavailable`（回放 1840 次 / 真实段 13 次）
- `Always Be Ready to Take Control`（回放 133 次）
- events: `bigModelLoading`（7486）、`steerOverride`（3057）、`pcmEnable`
- 全链 alive：carState/selfdriveState/controlsState/radarState/pandaStates/deviceState 全部正常

**没能复现的：`commIssue`。**
原因很明确——camera-less 模式下 modeld 从未启动（modelV2/longitudinalPlan alive 恒为 0），"进程从有到无"的断流场景不存在，所以 `not_alive` 判定不会触发。

结论：**诊断回放能复现 NO_ENTRY 类告警（wrongGear/sunnypilot Unavailable/steerOverride），但无法复现依赖真实 modeld 的 commIssue**。要覆盖后者，必须在设备上构建 replay 二进制（喂 visionipc 帧让 modeld 真跑），这是工具下一步的增强点。

## 2. 真实警告清单与真正原因

### 2.1 sunnypilot Unavailable —— 不是 bug，不用修
它是 `events_base.py:195 NoEntryAlert` 的默认第二行文本，几乎所有 NO_ENTRY 事件（wrongGear/reverseGear/seatbelt/preEnableStandstill）都会显示。回放里刷屏是因为车静止、挡位不对；真实段出现 13 次同理。属正常提示。

### 2.2 commIssue（seg-21、seg-22）—— 唯一真正的系统告警，根因是 Wi-Fi jetlink 大模型断流

seg-21 的 `commIssue reason=not_alive` 完整内容：
- `not_alive`: modelV2, longitudinalPlan, deviceMotion, liveLocationKalman, vehicleParameters, driverAssistance（**整套 model + 定位输出同时断**）
- `invalid`: extrinsicsCalibration, driverMonitoringState, radarState, lateralDelay, lateralTorqueParameters

seg-21 同时刻的 jetlink 时间线（同一秒 20:24:25）：
```
jetlink: large model failed mid-drive, back to the small model (failure 4, drop 7)
jetlink: next attempt in 5 s
jetlink: lost jetlink, port sees no host (cc 0); drop 7
jetlink: fallback frame 1909 ms: link 1882, demote 4, small model 23
jetlink: dialed 192.168.7.216 over Wi-Fi (5 GHz)
jetlink: link ready, waiting for a window to swap
```
**因果链：Wi-Fi 链路抖动 → 大模型 failed → 连小模型兜底都延迟 1909ms → modelV2 等 6 路消息同时 not_alive → selfdrived 报 commIssue → softDisable → longActive 掉 → 红灯不停/停车失效。**

### 2.3 关键对照：jetlink 抖动是必要不充分条件
全 route 分段统计：
- seg-3/12/14/17/19 都有 `large model failed` 或 `lost jetlink`，但 **comm=0**
- 只有 seg-21（jetfail=1）和 seg-22（紧邻前段失败）**comm=1**

区别：seg-21 是"大模型失败 + 完全丢链路 + fallback 1909ms"三重叠加；其他段只是大模型降级、小模型正常接管，modelV2 没断。

## 3. 代码哪里需要修

### 3.1 现有防护（已在设备上，主线无更新版）
`selfdrived.py:603`：
```python
big_model_settling = self.big_model_loading or time.monotonic() < self.big_model_ready_t + warmup_sec or self.model_events.settling
if not self.sm.all_checks() and no_system_errors and not big_model_settling:
```
`CommIssueGrace`（safety_guards.py:102）：not_alive / not_freq_ok **立即上报不 grace**，仅 invalid_only 有 grace。

### 3.2 真实边界缺陷（建议修，未改）
1. **`big_model_ready_t` 只在 `big_failed` 边沿更新**（selfdrived.py:314）。jetlink 的 `next attempt in 5 s` 与 `warmup_sec=5` 正好相等，重试+重连+swap 整个周期 >5 秒时，5 秒保护窗口会出现空档，此时 not_alive 直接穿透成 commIssue。
   - 建议：大模型失败/重试期间（ChestnutActive 翻转或 bigModelFailed 持续期）持续刷新 `big_model_ready_t`，而不是只在边沿刷。
2. **`model_unavailable` 要求 `seen['modelV2']`**（selfdrived.py:311）。模型切换导致 modelV2 首次未达时 seen=False，即使整组断流也不计入 failed，保护不生效。
   - 建议：用 `ChestnutActive` + `big_model_failed` 作为主判据，modelV2 seen 作为辅助，别让它成为必要条件。
3. **not_alive 无 grace 的设计对"链路抖动"过于刚性**。真进程崩溃应立即报（合理），但 jetlink 大模型是可恢复的外部依赖，其短暂断流不应等价为 IPC 故障。
   - 建议：把 modelV2/longitudinalPlan/deviceMotion/liveLocationKalman/vehicleParameters/driverAssistance 这组"模型/定位输出"在 `big_model_*` 状态下单独走一个短 grace，而不是完全豁免（否则会掩盖真崩溃）。

### 3.3 不需要修的
- sunnypilot Unavailable / bigModelLoading / steerOverride / wrongGear / preEnableStandstill：均为正常状态提示。
- 主线没有"已修但没装机"的 commIssue 补丁——设备与主线这段逻辑相同，**不是漏装机问题**。

## 4. 建议优先级
1. 最高：把用户切到 **USB**（JetlinkLink=1）复测同一场景。9-04 无大模型、10-18 USB 大模型（big 100%、零切换、longActive 87%、stopping 8759 帧）都停得很好；Wi-Fi 是所有 commIssue 的共同背景。这是零代码风险的验证。
2. 中：按 3.2 加固 big_model_settling 保护窗口（需回归 test_comm_issue / selfdrived 相关单测）。
3. 工具：给 diag_replay 加 replay 二进制构建路径，使 commIssue 也能车下复现。
