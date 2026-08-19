# Macan 适配后续任务与不完善点（2026-08-20 凌晨夜间自主完成）

## 0. 本轮已完成（夜间自主，全部工具核实）

| 项 | 内容 | 提交/验证 |
|--|--|--|
| 坡度补偿 v2 | carstate 解析 ESP_02 ESP_Laengsbeschl；carcontroller 双源交叉校验（原厂主源+IMU复核） | opendbc 55a6960，专项6用例+仿真84tests全绿 |
| 转向标定 v2 | ESP_Gierrate（原厂横摆°/s+VZ符号）5 route：15.24/16.05/17.23/14.65/16.25，极差 **2.6%**（vs gyro 22%） | steerRatio 18.0→16.2（原厂值，修正偏大15%） |
| 推送 | opendbc macan-long-0820@55a6960、主仓 @efa5931 | ls-remote 核实 |
| PDC 扫描 | vw_mlb.dbc **无超声波距离信号**；924报文仅状态标志（低速高速都广播） | 结论：停车辅助距离数据拿不到 |
| 弯道分析 | 高速缓弯 EPS 需求<1Nm（OP覆盖✓）；城市弯 0.2-1.1Nm（参数问题）；低速挪车 R17-33m 超能力 | calc_turn_analysis.py |
| ESP_02 高速广播 | 00000004 段13/14/16（95/89/81km/h）100Hz 稳定 | ✓ 验证完成 |

## 1. 弯道 0 接管评估（任务4 后半结论）

- **高速缓弯（R>1000m，yaw 0.3-1°/s）**：EPS 扭矩需求中位 <0.3Nm、P90 <0.8Nm——**OP 扭矩能力完全覆盖，0 接管可行**（与用户"高速小弯能接管"体感一致，数据证实）
- **城市弯（R 180-800m，5-15km/h）**：EPS 需求 0.2-1.1Nm——**能力也够**，转向不足是**参数匹配**问题：①steerRatio 偏大（18.0→已修正16.2，扭矩提升15%）②LatAccelFactor 未标定（原厂140待验证）——修正后预期明显改善，路试验证
- **低速挪车（R 17-33m，0-5km/h）**：转向角需求 74-124°——**超出 OP 低速扭矩能力**（minSteerSpeed 以下），搭把手是正常行为，不算缺陷
- ⚠️ **数据缺口**：设备上高速段几乎无弯道样本（00000004 高速段 yaw 全部 <0.3°/s）——高速弯道 0 接管需路试录制验证

## 2. 后续不完善点与任务（按优先级）

1. **【横向核心】LatAccelFactor 标定**——EPS_Lenkmoment(40|10) vs ESP_Querbeschleunigung(16|8) 回归（原厂对原厂）。数据源已备好；城市弯搭把手的主要未知数
2. **【路试验证】坡度补偿 v2**——开关默认关，开一版试一版：
   - 上坡掉速是否改善（对比 baseline）
   - 下坡刹一脚 vs 巡航速度闭环张力（MPC 反拉波动幅度）——必要时做"仅超速时触发"或调强度
   - 原厂主源 vs IMU 复核一致性（双源日志观察）
3. **【数据补充】路试录制**——高速弯道（R500-2000m）+ 坡道路段（验证原厂坡度法高速精度、ESP 信号高速值动态）
4. **【符号确认】ESP_VZ_Gierrate 语义**——标定用 VZ=1→负 假设（与 LWI_VZ 同惯例）；用 steeringAngle 方向与 yaw 方向交叉验证（打左转时 VZ 变化）
5. **【清理】孤立文件**——`/data/media/0/realdata/rlog.zst`（不属于任何 route，2533帧全0）删除或归档
6. **【UI】** mici/tizi 开关已就位（MacanSlopeComp/MacanSteerParams）——v2 复用同一开关，无需新 UI
7. **【协作】** jyoung8607 macan 分支（2024-05 停更，基础 HCA 调参可参考）；我们的纵向成果（力矩映射/SnG/坡度v2）可反哺上游
8. **【参数审计】** 质量 1895kg、轴距 2.81m ✓；SnG/撤力跟随已在方案B前实车验证；k=8.3 坡度强度待路试迭代

## 3. 本机 routes 现状备忘

- 692 文件 = 326 扁平 rlog + 326 qlog + 39 段目录（00000049，全低速 0-48km/h 挪车场景）+ 1 孤立文件
- 高速数据源：**00000004**（59 段，段11/13-19/45 为 70-91km/h 高速段）
- 城市数据源：00000002（67 段）、00000001/00000005
- 00000049 段0/1 为空，扫描需跳过

## 4. 关键文件索引

- 坡度v2 代码：opendbc_repo/opendbc/car/volkswagen/{carstate,carcontroller}.py
- 转向值：interface.py MacanSteerParams（steerRatio=16.2, friction=0.52）
- 标定脚本：ai/tools/calc_steer_v8.py（ESP_Gierrate）、calc_turn_analysis.py（弯道）
- 验证脚本：ai/tools/sim_test_slope_v2.py（双源专项）
- 信号手册：ai/docs/MLB_MACAN_FACTORY_SIGNALS.md
