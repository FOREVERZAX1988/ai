# Macan 雷达测距标定 —— 方案A（纯CAN信号反推，不用视觉）

状态：2026-09-09 方案A 定义、实测可行性核查（0004 全59段 + 0002 全67段）

## 核心结论（已实测验证）
1. **UI 右侧车距来源**：`chevron_metrics._draw_lead` 用的 `radarState.leadOne`，
   即 `radard.get_lead()` 的**融合输出**（vision lead 匹配雷达 Track 的卡尔曼平滑；
   无雷达轨道匹配时回退纯视觉 `get_RadarState_from_vision`）。→ **不是纯视觉、也不是纯雷达，是融合后**。
   - 实测：0004 seg20 radarState leadOne.dRel 1200帧 vs 视觉 leads 1131帧——几乎1:1。
     dRel 范围 10.5~92.8m，随视觉深度波动。→ 确认无独立雷达轨道，就是视觉 lead 回退/融合。
2. **雷达自身 TTC 不可得**：`PCF_01(0x323).PCF_Time_to_collision` 与 `PCR_01(0x322).PCR_Obj_TTC`
   在全部扫描（route 0004×59段、0002×67段，任意src）均 0 帧。Macan MLB 雷达不把 TTC 暴露到可观测 CAN。
   → 用户"用雷达TTC d=TTC×vrel 逆推距离"的思路，**无法从现有 logs 直接实现**。
3. **CAN 里能用的信号**（均有）：
   - `ACC_02(0x30c,src2).ACC_Abstandsindex` idx @24|10 (1,0) [1|1021]
   - `ACC_04(0x324,src2).ACC_Geschw_Zielfahrzeug` 前车绝对速度 @40|10 ×0.32 **km/h**（无目标=327.36；用户确认单位是 km/h）
   - `ESP_03(0x103,src0/1/130).*Radgeschw` 轮速 → v_ego；carState.vEgo

## 方案A：相对速度微分闭合标定（纯CAN，无视觉）
几何事实：锁定前车时，ḋ = vrel = (v_lead − v_ego)，其中 v_lead 单位 km/h（÷3.6 转 m/s）。
而 d = F(idx) = t(idx)·vEgo（时距模型）。差分：t(idx_{i+1})·v_{i+1} − t(idx_i)·v_i = vrel·dt
→ 构造成链式最小二乘解出 t(idx) 单调表。
锚点：最小 idx（近贴车，t≈0.8s）。不引入任何视觉参考。

## 本轮实测可行性（route 0004 全59段 + 0002 全67段）
### 有效跟车样本统计
- 0004：59 段全为**低速城市路**（maxV 最高 26.3 km/h，多数 8-16 km/h）。CAN idx 大量有效帧 + vlead 有值。
- 0002：67 段中仅 seg11/12/13/15/16 有有效前车速度（743/1129/152/909/154 帧），其余段无目标。
### 方案A 拟合尝试（0002 seg11,12,13,15,16 → 20908 跟车样本 / 4 轨迹 / 49 差分约束 / 37 节点）
- **结果：全部节点时距被压平为同一常数 0.651s，无有效区分度。**
- 根因：差分约束不足（49条 vs 37未知数）+ 城市低速 idx 大尺度步进极稀少
  （0004 各行驶段 idx 步进≥10 的仅 1-3 次/段）。
- **结论：现有 0004/0002 数据全部为低速城市跟车，无法满足方案A所需的
  "稳定高速跟车、idx 大跨度缓变、vrel 连续非零" 样本 → 统计上不可行。**

## 与旧视觉标定的差异
- 旧表（radar_interface.py `_macan_abstands_t/_macan_abstands_idx`，153点）用视觉 lead prob>0.5 做参考，
  且做了视觉系统性偏 ~1m 的 -1m 修正——这是其误差来源，方案A 本想规避。
- 但方案A 受限于**缺少高速稳定跟车路试数据**，当前无法构建可替换旧表的可靠表。

## 下一步（达成方案A 的可执行路径）
1. **采集一段高速稳定跟车**（前车非静止、idx 大跨度缓变、vrel 连续非零、vEgo>60km/h）专属路试
   → 补足方案A差分约束，才能可靠反推 t(idx)。
2. 若补采后 CAN-only 表单调性/留出误差优于旧视觉表 → 替换 `_macan_abstands_t`。
3. 或考虑混合方案：用雷达 idx 跨车速交叉对应（同一 idx 在两种车速下的 d/v 稳定性）做半自动标定，
   对低速数据更有鲁棒性（绕开微步进失效问题）。

## 参考文件
- 旧视觉标定脚本 ai/tools/recalibrate_abstandsindex.py / discriminate_abstandsindex.py
- 方案A拟合脚本（本轮新写）ai/tools/fit_abstands_canonly.py
- 表 _macan_abstands_t/_macan_abstands_idx 在 opendbc_repo/.../volkswagen/radar_interface.py 与 carcontroller.py
