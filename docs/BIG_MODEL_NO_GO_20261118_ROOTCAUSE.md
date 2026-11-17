# 大模型接管后"车子不肯前进"根因判定——不是 HEVC

日期：2026-11-18
用户问题（11-17 21:07）："大模型突然起来了，激活纵向后，前面没车，但车子就是不前进，慢慢开一段就停下来，开一段就停下来。踩刹车退出纵向，车子动了，再激活纵向，一样停住。"问：是不是 HEVC 导致？

## 结论（一句话）
**不是 HEVC、不是 Wi-Fi 链路、不是模型传输错误。** 是 E2E 实验模式下，**大模型在低速场景自己持续输出 -0.2 m/s² 减速 + shouldStop**，把车压停。这是模型的产品行为，**不建议硬修代码覆盖它**（遵循用户 11-17 21:18 原则）。

## 决定性证据（route 00000031--b7b6c905ad，seg18-24，20:21-20:27）

### 1. 现象精确定位（seg23）
逐帧时间分布，完美复现用户"走→停→走→停"：
```
+1404-1410s  shouldStop 0%   vEgo 1.84→0.73 m/s（在走）
+1412s       shouldStop 54%  vEgo 0.20（模型开始说停）
+1414-1418s  shouldStop 90-100% vEgo 0（停住）
+1420-1430s  shouldStop 0%   vEgo 1.09→0.56（又走）
+1432-1434s  shouldStop 85%  vEgo 0.06（又停）
```
`shouldStop` 来自 `modelV2.action.shouldStop` → `longitudinalPlanner.py:398/434`，是模型直接输出的语义位。

### 2. 排除 HEVC / 链路（四重证据）
| 机制 | 证据 | 结论 |
|---|---|---|
| HEVC 压缩质量 | 之前像素误差实验 MAE 0.53/255、无 range 折叠 | 已排除 |
| held 帧重复 | seg23 desiredAccel 有 **408 个唯一值**、连续分布 -0.18~-0.25 | 排除 |
| 链路抖动/丢帧 | seg23 全程 HEVC 日志只有 encoder 4 条，**无 lost link/fallback/large model failed** | 排除 |
| 时序/帧延迟 | seg23 modelV2.frameId 27603→28802 **完美连续递增**，零重复、零跳变、dt=0.05s(20Hz) | 排除 |
| **反证** | 链路最差的 seg21（lost jetlink + fallback 1909ms）反而 shouldStop=0%、车正常走 2.17m/s | 因果反转 |

### 3. 根因：大模型 E2E 低速输出（对照实验）
| 段 | 模型 | aTarget | vTargetNow | 车速 |
|---|---|---|---|---|
| seg20-21 | 小模型 | **≈ 0.00** | 2.13~2.17 | 正常走 2.1 |
| seg22-24 | **大模型** | **-0.20 恒定** | 1.36→0.69→0 | 走走停停 |

- vCruise = 29.8 m/s（107 km/h，用户设定的高速巡航），但大模型把 vTargetNow 压到 0~1.5 m/s
- aTarget 与 modelV2.action.desiredAcceleration **逐帧完全相同**（-0.20/-0.20）——直接透传模型输出，planner 没加工
- leadOne.present=False 全程（无前车）、brakePressed=0、gear=drive —— 不是前车/刹车/挡位导致
- `shouldStop=False` 时 aTarget 仍是 -0.204 —— **模型一边说"不用停"、一边持续减速**，这正是"慢慢开一段就停"的元凶

### 4. 代码层定位（为什么模型输出能直接压制车）
`longitudinal_planner.py:423-434`：
```python
candidates = [(a_mpc,...), (a_cruise,...)]
if is_e2e: candidates.append((output_a_target_e2e, e2e, output_should_stop_e2e))
output_a_target = min(candidates, key=lambda c: c[0])   # 取最小 accel
self.output_should_stop = any(should_stop for ... in candidates)  # OR
```
`is_e2e()` = `ExperimentalMode`（当前设备 = True）。所以大模型的 -0.2 比 cruise 候选小，被选中持续减速；模型 shouldStop=True 时 OR 生效停车。
**这段逻辑与上游 cnb/master 完全一致**（git diff 为空），不是 fork 自加 bug。

## 为什么"USB 正常、Wi-Fi 不行"的猜测不成立
- 设备当前 JetlinkLink=1（USB），但出问题的 20:00 段跑的是 Wi-Fi（日志有 dialed 192.168.7.216 over Wi-Fi）
- 然而 seg23 的 Wi-Fi 链路**完全干净**、帧号完美连续，模型输出是真实连续值——没有传输错误的任何痕迹
- 合理的解释：用户记忆中的"USB 正常"可能是不同场景（如高速巡航、无低速停车工况）。**同一段路做 USB/Wi-Fi A/B 才能最终确认传输方式是否有影响**，但现有证据强烈指向模型本身。

## 给用户的选项（不擅自改代码）
按用户原则"不能因为模型的问题硬修代码"，我没有动 E2E/模型相关代码。可选：
1. **零代码验证**：同一段路，E2E 实验模式开/关各跑一次。关掉后车正常走（E2E 候选不参与），即可确认是模型输出；这也是日常使用的规避方法。
2. **A/B 复测**：同一段路 USB vs Wi-Fi，确认传输方式是否有差异（当前证据倾向无差异）。
3. **联系模型方**：把 seg23 的 `modelV2.action.desiredAcceleration` 持续 -0.2 但 shouldStop=False 的不自洽输出反馈给模型训练方——这是模型输出层的问题，不该在车端硬修。
4. 若用户明确要求车端兜底：可在 `update_e2e_target` 加"shouldStop=False 且低速持续减速 N 秒时退出 e2e 候选"的守护，但这**覆盖模型意图**，必须用户书面确认后才做。

## 附：设备/参数状态
- 当前 JetlinkLink=1（USB）、ExperimentalMode=True
- 前一天修复（f61dc9f2b / 设备 590db4a2e）不受影响，comma active、pandad 正常
