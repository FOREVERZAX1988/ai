# Macan 纵向调优参数地图

> 2026-08-26 整理。按控制链路分层，每个参数标注：作用层 / 机制 / 数据依据 / 当前值 / 状态（✅已验证 / 🆕待路试 / ⚠️有副作用）。
> 调优原则：**风格类调决策层（换模型收益最大），执行类调执行层，控制层只做兜底**。

---

## 控制链路总览

```
感知层
├─ 模型(modelV2) → desiredAcceleration(e2e意图) + 路径/曲率
├─ 雷达融合(radarState.leadOne) → 前车 dRel(距离)/vLead(速度)
└─ carState → vEgo(车速)/aEgo(实际加速度)/vCruise(设定速度,km/h!)/踏板

① 纵向planner → 选source(e2e/MPC/cruise)、产出 aTarget + shouldStop
② LongControl(状态机+PID) → accel请求(actuators.accel) ← aTarget 变平顺
③ CarController → 力矩/减速请求 → CAN帧 ← accel 变成车能懂的
④ 原厂ACC(ACC_05) → st状态机(0关/2待机/3激活/4超驰/6故障) + 执行
```

**三层心智模型**：
- `aTarget`：模型/算法说"我想要这个加速度"（意图）
- `accel请求`：longcontrol说"我这样平顺地逼近它"（PID+feedforward+限幅）
- `力矩/Verz`：carcontroller说"我让原厂执行"（+坡道补偿/超驰/同步）

---

## 决策层（模型/MPC）——风格主导，换模型收益最大

| 参数 | 机制 | 数据依据 | 当前值 | 状态 |
|---|---|---|---|---|
| `LongitudinalPersonality` | 跟车风格：0激进/1标准/2从容 → T_FOLLOW(1.25/1.45/1.75s) + jerk惩罚 | 005f/0060实测 | **2（从容）** | ✅已验证 |
| e2e模型（模型中心） | 无前车时模型直出desiredAcceleration | 0060:78%走e2e | NNMV2 | ✅已验证 |

**说明**：纵向体验的"灵魂"在模型。继续堆控制层参数是给模型的fallback打补丁——修复类必要，风格类可疑。

---

## 控制层（planner/longcontrol）——兜底，修复类必要

| 参数 | 机制 | 数据依据 | 当前值 | 状态 |
|---|---|---|---|---|
| `MacanCruiseCoastEnable` | 巡航滑行带总开关：带内(±band)输出0滑行 | 0060:81%时间accel非零=振荡 | **关** | 🆕待路试 |
| `MacanCruiseCoastBand` | 滑行带宽度(m/s)：0.4≈±1.4km/h | 原厂Mom=0占75%（不推车） | **0.4** | 🆕待路试（可试1.0） |
| `MacanJerkLimitEnable` | accel变化率限幅总开关 | 0051 vs 原厂0.48vs0.35过冲 | **关** | ⚠️SnG副作用已修 |
| `MacanJerkLimit` | 限幅值(m/s³)：0.2=缓升 | 0060:41%时间限幅生效 | **0.0** | ⚠️SnG副作用已修 |
| `MacanAccelDeadzoneEnable` | aTarget死区总开关：|aTarget|<dz归零 | 4f:MPC在0附近抖动→mom开合喘气 | **关** | ⚠️未验证 |
| `MacanAccelDeadzone` | 死区宽度(m/s²) | 同上 | **0.1** | ⚠️未验证 |
| `MacanAccelLimit` | 加速度上限(m/s²)：0=原厂曲线 | 4f:aTarget>1.0占20%激活时间 | **0.0** | ⚠️未验证 |

**SnG起步豁免**（longcontrol.py，已修）：jerk限幅在pid+vEgo<3m/s时跳过——0060实测jerk=0.2时accel爬3s车不动→MPC撤回起步。

---

## 执行层（carcontroller）——校准，与模型无关

| 参数 | 机制 | 数据依据 | 当前值 | 状态 |
|---|---|---|---|---|
| `MacanSlopeComp` | 坡度补偿：IMU坡度→g*sin(slope)加到accel | 下坡滑/上坡无力 | **开** | ✅已验证 |
| `MacanSlopeCompUnlimited` | 放开原厂力矩限制（选项2） | 小坡度补偿空间 | **关** | ✅已验证 |
| `MacanStartStop` | SnG起步跟停：视觉决定起步+代发RESUME | 005f/0060实测 | **开** | ✅已验证 |
| `MacanStartStopDistance` | 起步安全距离(米)：0=纯意图/3-10=需雷达 | 拥堵防加塞 | **5** | ✅已验证 |
| `MacanCornerLimit` | 弯道纵向限制：|angle|>5°压低上限 | 4f:62%加速在弯道 | **关** | ✅已验证 |
| `MacanRadarFusion` | 雷达融合：bus2原厂距离+速度修正视觉lead | 0058:融合后p90=801cm | **开** | ✅已验证 |
| `MacanStartupGapSync` | 开机距离档同步：DIST脉冲同步原厂ACC | 双向同步 | **关** | ✅已验证 |

---

## 安全适配层——必须，已验证

| 机制 | 实现 | 数据依据 | 状态 |
|---|---|---|---|
| 超驰阈值5% | `pedal_value>5.0`判定超驰 | 34样本：原厂确认阈值≈6-17%(中位9%) | ✅已验证 |
| 点火毛刺抑制25s | `frame>2500`才采信踏板 | 005e/005f点火初期踏板毛刺实锤 | ✅已验证 |
| 原厂状态同步 | 原厂st∉(3,4)→OP降级 | 00000033:矛盾窗口→DTC锁ACC | ✅已验证 |

---

## 调优优先级（建议顺序）

1. **换e2e模型**（决策层）：模型中心77个可选，A/B对比005f/0060纵向风格——收益最大
2. **控制层兜底**：滑行带（band 0.4→1.0）修巡航振荡；jerk限幅默认关（释放模型节奏）
3. **执行层校准**：坡道补偿（已开）；力矩映射（如需）
4. **安全层**：不动（已验证）

---

## 已验证结论（数据实锤）

- **超驰5%**：34样本（00000049×9+0002×25）原厂确认阈值≈6-17%(中位9%)，OP5%提前让位=安全方向
- **点火25s**：005e/005f点火初期踏板毛刺（16→39爬升19s/190尖峰0.1s），25s窗口覆盖
- **滑行带方向**：原厂Mom=0占75%（不推车）vs OP accel非零81%（主动干预）——OP缺"不推车"区间
- **SnG豁免**：0060 jerk=0.2时accel爬3s车不动→MPC撤回；005f无限制0.5s转正起步成功

---

## 待路试（开关默认关，开一版试一版）

1. **MacanCruiseCoastEnable** + Band=0.4（或1.0）：巡航感受滑行（不再忽快忽慢）
2. **MacanJerkLimitEnable** + 0.2：跟车停车起步2-3次（验证SnG自动起步）

---

## 新增参数检查清单（§3b）

1. `params_keys.h`注册 → 重编译`libparams_c.so`
2. tizi布局（volkswagen.py）：控件+DESCRIPTIONS+回调+items+set_visible
3. mici布局（toggles.py）：控件类+三处接入+visible联动
4. **po翻译（CHS/CHT各2条msgid）**——漏掉=中文UI显示英文
5. 参数读取：BOOL用get_bool、FLOAT用get(return_default=True)+1秒缓存
6. py_compile+UI重启生效
7. 提交推送：同名分支、--no-verify、ls-remote核实
