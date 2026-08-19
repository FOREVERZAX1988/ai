# Macan/MLB 原厂信号手册（routes 扫描归纳，2026-08-19）

> 扫描方法：`ai/tools/probe_all_signals.py`（v3 优化版）——20 个关键信号 × 19 个 route × 每 route 前 2 段 × 12000 帧
> 数据源：vw_mlb.dbc 位定义 + 本机全部 rlog（326 扁平 + 39 段目录 = 365 个 rlog）
> 完整统计表：`ai/tools/signal_scan_output.txt`
> 用途：坡度补偿 v2（原厂信号源）、转向标定 v2（原厂横摆角速度）、LatAccelFactor 标定（原厂横向加速度）

## 0. 结论速查（先读这个）

| 信号 | 报文 | 可用性 | 用途 |
|--|--|--|--|
| **ESP_Laengsbeschl** | ESP_02@257 | ✅ **主信号** | 坡度推导（原厂纵向加速度，大动态 -10.5~+1.75 m/s²） |
| **ESP_Querbeschleunigung** | ESP_02@257 | ✅ 稳定 | LatAccelFactor 标定（原厂横向 g） |
| **ESP_Gierrate + ESP_VZ_Gierrate** | ESP_02@257 | ✅ 稳定 | steerRatio 标定（原厂横摆角速度，度/秒+符号位） |
| TSK_Steigung | TSK_05@273 | ⚠️ 大部分无效 | 变速箱坡度%（原始码0=无效，仅少数段±1.6%） |
| PSD_Endsteigung | PSD_01@929 | ❌ 不可用 | Macan 未广播（全 route 全 0） |
| ACC_Momentenanforderung | ACC_05@269 | ✅ | 原厂力矩请求（0000004c 实测 177Nm 起步） |
| ACC_Verz_anf | ACC_05@269 | ✅ | 原厂减速请求（3.01=未激活；实测 -0.515） |
| ACC_Gesetzte_Zeitluecke | ACC_02@780 | ✅ | 车距档位（3-4，用户习惯 4） |
| EPS_Lenkmoment | LH_EPS_03 | ✅ | EPS 转向扭矩（0.01Nm/位，实测 0-2.49Nm） |
| ACC_Status_ACC | **ACC_05@57\|3** | ⚠️ dbc 有两个定义 | ACC 状态（ACC_01@60\|3 是雷达状态，勿混用） |
| TSK_Status | @16\|2 值0-3 | ✅ | 巡航状态（报文待确认） |

## 1. 坡度类信号详解

### 1.1 ESP_Laengsbeschl（ESP_02，报文 257）——坡度推导主信号 ✅

- 位定义：`24|10@1+ (0.03125,-16)`，单位 m/s²，范围 [-16, 15.9]
- 实车观测：多 route 广播稳定；**大动态**：-10.5（重刹≈1g）、+1.75（起步加速）、-5.4~+1.1（行驶加减速）；非零比 16-94%
- **坡度推导公式**：`坡度% ≈ (ESP_Laengsbeschl − aEgo) / g × 100`
  （ESP 传感器测的是沿车体轴的总加速度 = 运动加速度 + 重力分量；aEgo 是速度微分=纯运动加速度；相减得重力分量）
- **优势**：车体 ESP 单元内置传感器（仪表 G-meter 同源），比挡风玻璃设备 IMU 抗振、精确、无安装角标定问题
- **注意**：ESP_02 在哪些段广播需确认（00000049 前 2 段未扫到——该 route 段 0/1 可能极短或空）

### 1.2 TSK_Steigung（TSK_05，报文 273）——不可靠 ⚠️

- 位定义：`40|8@1+ (0.8,-101.6)`，单位 %，范围 [-101.6, 102.4]
- 实车观测：**原始码 0 = -101.6%（无效标记）**；多数 route 为 0 或无效；仅 00000037/38/47/4c 有 ±0.8~1.6% 小值（低速小坡）
- TSK_QBit_Steigung（@12|1）偶发 1（有效语义待确认）
- **结论**：低速段基本不可用（值为0/无效），未验证高速坡道段——**不推荐做主源**（除非后续在坡道路试段验证）

### 1.3 PSD_Endsteigung（PSD_01，报文 929）——不可用 ❌

- 位定义：`54|5@1+ (0.5,0)`，单位 %，范围 [0,14.5]
- 实车观测：**全部 route 全 0**（Macan 未广播该报文的有效内容）——排除

## 2. 标定类信号（解决当前标定不可靠问题）

### 2.1 ESP_Gierrate + ESP_VZ_Gierrate（ESP_02@257）——steerRatio 标定正解 ✅

- ESP_Gierrate：`40|14@1+ (0.01,0)`，单位 **度/秒**（DegreOfArcPerSecon），范围 [0,163.82]——**无符号幅值**
- ESP_VZ_Gierrate：**符号位**（0=正/1=负？需确认，0000003f 86% 为 1）
- 实车观测：中位 0.1-0.27（直行≈0）、max 18.95°/s（=0.33 rad/s 弯道）——广播稳定
- **真实 yawRate(rad/s) = Gierrate × 0.01 × π/180 × sign(VZ)**
- **价值**：替代 gyro.z（设备陀螺仪）做 steerRatio 标定——之前 gyro 标定跨 route 极差 22% 不可靠（偏置漂移 0.0066~0.0153），原厂信号应大幅改善
- 注意：可与 ESP_Querbeschleunigung 交叉验证：ay ≈ v × yawRate

### 2.2 ESP_Querbeschleunigung（ESP_02@257）——LatAccelFactor 标定正解 ✅

- 位定义：`16|8@1+ (0.01,-1.27)`，单位 g，范围 [-1.27, 1.27]
- 实车观测：多 route 广播稳定；低速段 ±0.06g（小弯）；高速弯段（00000049）需补充验证
- **价值**：LatAccelFactor 标定 = EPS_Lenkmoment vs ESP_Querbeschleunigung 回归（原厂对原厂，最干净）——替代"gyro×v 算侧向加速度"的间接法（之前 55 帧相关仅 0.258 不可靠）

### 2.3 EPS_Lenkmoment（LH_EPS_03）✅

- 单位 0.01Nm，范围 [0,2.49]Nm（实测）；0000003f 中位 2.13Nm（行驶），00000038 中位 0.45Nm
- 配合 ESP_Querbeschleunigung 做 LatAccelFactor 回归

## 3. ACC 纵向信号（原厂行为参考）

| 信号 | 报文 | 位定义 | 实车观测 |
|--|--|--|--|
| ACC_Momentenanforderung | ACC_05@269 | 力矩请求 1Nm/位 | 0000004c **177Nm**（起步/加速）、00000038 57、00000037 27——验证原厂动态范围 |
| ACC_Verz_anf | ACC_05@269 | 减速请求 (0.005,-7.22) | **3.01=未激活**（多 route）；0000004c **-0.515**（实际减速） |
| ACC_Freigabe_Momentenanf | ACC_05@269 | 使能 0/1 | 00000037/38/3f/4c 有 1（力矩通道激活段） |
| ACC_Freigabe_Verzanf | ACC_05@269 | 使能 0/1 | 00000037/3f/4c 有 1（减速通道激活段） |
| ACC_Gesetzte_Zeitluecke | ACC_02@780 | 档位 1-4 | 3-4 档（默认3、用户习惯4）——与记忆一致 |
| ACC_Status_ACC | **ACC_05@57\|3** | 0-7 | ⚠️ **注意 dbc 有两个定义**：ACC_01@60\|3（雷达状态）与 ACC_05@57\|3（ACC 控制状态）——OP 代发和状态判断用 **ACC_05 的**，扫描脚本曾误读 ACC_01 |

## 4. routes 现状与整理建议（2026-08-19 实测）

- realdata 共 **692 个文件** = 326 扁平 rlog + 326 扁平 qlog + 39 段目录 rlog（00000049）+ 1 个孤立文件
- **孤立文件**：`/data/media/0/realdata/rlog.zst`（不属于任何 route，2533 帧，信号全 0）——整理时可移除/归档
- **混合格式**：00000002/00000001 等为扁平（`route--hash--seg--rlog.zst`），00000049 为段目录（`route--hash--seg/rlog.zst`）——openpilot 两种都支持，**不建议大规模移动**（风险：断链/丢失）；需要时按 route 前缀分组即可
- 扫描注意：00000049 前 2 段未扫到信号（段 0/1 极短或空），后续扫描应跳过前 2 段或从有数据的段开始

## 5. 后续实施计划（信号已备好）

1. **坡度补偿 v2（双源判定）**：主=ESP_Laengsbeschl 推导坡度，复核=IMU slopePct（现有链路）；交叉校验 |差|<3% 用主源，超阈值降级
   - 实现：carstate.py 解析 ESP_02 → carcontroller 算原厂坡度 → 双源选择 → mlbcan（参数接口不变）
2. **转向标定 v2**：用 ESP_Gierrate（°/s×VZ 符号）替代 gyro.z——重跑 calc_steer，期望解决跨 route 极差 22% 问题
3. **LatAccelFactor 标定**：EPS_Lenkmoment vs ESP_Querbeschleunigung 回归——替代 gyro×v 间接法
4. 上述完成后更新 `MLB_MACAN_ADAPTATION_GUIDE.md` 的标定值（实验值 → 可靠值）

## 6. 待确认项

- ESP_VZ_Gierrate 符号语义（0=正还是1=正——需方向盘打左/右的对照数据）
- ESP_02 在 00000049 高速段是否广播（扫描段 0/1 为空）
- ACC_Status_ACC 用 ACC_05@57|3 重新扫（确认状态 3/4/2/6 分布）
- TSK_Status 所在报文确认（@16|2 值 0-3）
