# Macan (PORSCHE_MACAN_MK1 / VW MLB) 适配指南——有效修改汇总

> 用途：为其他分支（dragonpilot / carrotpilot / iqpilot 等）移植 Macan 提供指导。
> 来源：sunnypilot `macan-long-0819` 分支实际验证代码（git log 核实）+ 多份 routes 实测。
> 原则：所有 commit 均经 git log 核实；所有数值均来自真实脚本输出（2026-08-19 验算）。

## 0. 平台背景（先读）

| 项 | 值 |
|--|--|
| 车型 | Porsche Macan MK1（VolkswagenMLBPlatformConfig，fingerprint=PORSCHE_MACAN_MK1） |
| DBC | vw_mlb（opendbc/dbc/vw_mlb.dbc） |
| 总线 | gateway 单 panda：CAN0=ADAS 网关(bus0)、CAN2=原厂 ACC 雷达域(src=2)、bus128=OP 代发帧 |
| 纵向 | 原厂 ACC 雷达（bus2），OP 代发 ACC_05(0x10D)；radarUnavailable=True（radarState 走视觉 modelV2.leadsV3） |
| 横向 | 纯扭矩控制（configure_torque_tune；MLB 无角度接口） |
| EPS 扭矩 | LH_EPS_03.EPS_Lenkmoment，单位 0.01Nm（[-251,237]→实际[-2.51,2.37]Nm） |
| 轴距 | 2.896 m |
| 转向比标称 | ~14.9:1（实测标定见 §4，跨 route 差异大） |

## 1. 纵向控制核心（opendbc/car/volkswagen/mlbcan.py `create_acc_accel_control`）

- 力矩基线：`full_cruise = 6.3*v_ego + 15`（00000004 原厂观测拟合：静止~27Nm、20km/h 48-52、100km/h+ 180-198）；低速斜坡 `27 + (full-27)*min(1, v/5.56)`
- 加速映射：`mom = min(500, cruise_torque + accel*85)`（加性，原厂斜率≈97，留 12% 余量防过冲）；减速 `scale = max(0, 1+accel*2.5)`
- 力矩斜坡：`_ACC_MOMENT_RAMP = 8Nm/帧 ≈ 400Nm/s`（起步柔和）
- braking 判定：`accel < -0.05`（00000039 seg5 实锤：旧阈值 -0.4 吞掉原厂 verz=-0.40 → st6）
- verz：加深斜坡 0.07/帧、最深 -2.2（原厂 -2.215）；**停车保持 verz=-2.0**（0000004c 坡道后溜实锤：OP -0.55 vs 原厂 -2.0）
- 撤力跟随：`stock_follow=True` 时力矩斜坡下降 3Nm/帧 镜像原厂（00000041/42 修复 controlsMismatch→TSK_04 退出）
- 方案A 力矩限制：`if stock_mom>0 and v_ego>3.0: mom=min(mom, stock_mom)`（v≤11km/h 豁免起步；cut-in 不再加速逼近，00000017 实证）
- 油门超驰：gas_override 时走 st=4 并发巡航力矩（00000042 seg3/6）
- 健康位：KD_Fehler=1（0000002e）；stopping 时 ax_Getriebe=1.63（00000039 seg7）
- acc_control 状态机：3=激活 / 4=超驰 / 2=待机 / 6=故障

## 2. SnG 起步跟停（0818 适配，macan-long-0818 分支）

- `update_stop_and_go`：停车保持 anh 代发 + 视觉判定起步（用户可开关 MacanStartStop）
- **aTarget 传参链**：controlsd_ext 读 `sm['longitudinalPlan'].aTarget` → `CC_SP.params`(key="aTarget") → carcontroller 读取 → SnG 判定（0000004d 实测：LoC 压 accel≤0，必须用 planner 原始 aTarget 而非 actuators.accel）
- 坡道起步三件套（opendbc 0fe65b5c）：解锁/保持力/斜坡
- 强制释放 anh + 请求正力矩（0158d0cd 修复自动起步 gap）
- 相关提交：主仓 `38bca41a0`(aTarget 传参)、`21d5e2ddf`；opendbc `60e6cdcd`(方案A)、`0fe65b5c`、`5f959cb4`、`0158d0cd`

## 3. 坡度补偿（0819 方案B，本次重点）

### 信号链路（三层，缺一不可）
1. **controlsd_ext.py**（主仓，sunnypilot 扩展）：`sm_services_ext` 加 `'accelerometer'` 订阅；重力投影算坡度：
   `slope_pct = (0.4571*ax - 0.0079*ay - 0.7667*az - 4.0412) / 9.81 * 100`
   （n=[0.4571,-0.0079,-0.7667]、s_ref=4.0412，00000049 标定；差值法——设备安装倾角被 s_ref 消掉）
   经 `CC_SP.params`（key="slopePct"）传给 carcontroller
2. **carcontroller.py**（opendbc）：帧首循环读 slopePct → `self.slope_pct`
3. **mlbcan.py**（opendbc）：`create_acc_accel_control(..., slope_pct=0.0, slope_comp=False, slope_comp_unlimited=False)`——
   `if slope_comp: accel_eff = accel + 9.81*sin(atan(slope_pct/100)) else: accel_eff = accel`
   braking 判定 / 力矩正负分支 / verz 目标**全部改用 accel_eff**（下坡 accel_eff<0 触发/加深刹车=“刹一脚”）
   原厂限制：选项1 `min(mom, stock_mom)` / 选项2（Unlimited 开）`min(mom, max(stock_mom,200))`

### 数据验证（真实脚本输出）
- 坡度信号有效：静止帧 3122 帧中位 **-0.11%**（≈0）、动态上坡 34% / 下坡 34%
- 超载仿真（00000049）：上坡 24972 帧超 500Nm 仅 **0.0%**；下坡 21748 帧 **97%** 触发 braking，verz -0.48~-2.13（坡度越大越深）
- 原厂 ACC 全速度段对坡度**欠补偿 4~8 倍**（3-8m/s k≈+1.0、8-15≈+0.5、15-25≈0~负 vs 物理需求 8.3Nm/坡度%）

### 相关提交
- 主仓：`ea1887505`(信号铺路)、`677c9ff`(参数+UI)
- opendbc：`adc1ff9a`(读 slopePct)、`6fc10a6`(mlbcan 参数化+interface 覆盖)

## 4. 横向标定（实验值，默认关）

| 参数 | 标定值 | 可靠性 |
|--|--|--|
| steerRatio | ≈18.0 | ⚠️ 跨 route 极差 22%（15.89/17.98/19.86），**不可靠，待路试** |
| friction | ≈0.52 | 中（~2000 帧） |
| latAccelFactor | 不覆盖（保持原厂 140） | 样本不足（55 帧，相关 0.258） |

- 覆盖位置：`interface.py _get_params` return 前（`candidate==CAR.PORSCHE_MACAN_MK1` 且 `MacanSteerParams` 开关开）
- yawRate 标定源：gyroscope.z 去偏置（偏置 0.0066~0.0153 漂移，需每 route 独立标定）；livePose 在这些 route 均无帧；liveLocationKalman 的 NED 差分噪声大（±π 跳变）
- 开关：`MacanSteerParams`（默认关=原厂值）

## 5. 参数与 UI（主仓 openpilot/）

### params_keys.h（openpilot/common/params_keys.h:240-244）
```
{"MacanStartStop", ...}            // 起步跟停
{"MacanSlopeComp", ...}            // 坡度补偿主开关
{"MacanSlopeCompUnlimited", ...}   // 坡度补偿-放开原厂限制（子选项，联动可见）
{"MacanSteerParams", ...}          // 转向系数（实验值）
```

### UI（两套，用户 tizi 用的是 sunnypilot 品牌设置页）
- **sunnypilot 品牌设置页** `openpilot/selfdrive/ui/sunnypilot/layouts/settings/vehicle/brands/volkswagen.py`：
  VolkswagenSettings 4 个 toggle_item_sp；仅 `carFingerprint=="PORSCHE_MACAN_MK1"` 可见；engaged 禁用；切换请求 OnroadCycleRequested
  **联动可见性**：Unlimited 仅当 MacanSlopeComp 开时显示（整行级 `set_visible`，勿用 action_item.set_visible——那只藏控件不藏行）
- **mici UI** `openpilot/selfdrive/ui/mici/layouts/settings/toggles.py`：4 个 BigParamControl；加进 add_widgets + _refresh_toggles；carFingerprint 判断可见性

### 翻译
- `openpilot/selfdrive/ui/translations/app_zh-CHS.po` / `app_zh-CHT.po`：**tr() 英语原文作 msgid + PO 中文 msgstr**，tizi 与 mici 共用（multilang 的 TRANSLATIONS_DIR 同一目录）
- 易错：`tr_noop` 文本必须二次 `tr()` 包裹才翻译（mads_settings.py 曾漏包显示英文）

## 6. 移植到其他分支（dragonpilot / carrotpilot / iqpilot）指导

### 文件清单
| 层 | 文件 | 改动 | 是否通用 |
|--|--|--|--|
| opendbc | mlbcan.py | create_acc_accel_control（§1 + §3 坡度参数） | ✅ 通用（各 fork 共享 opendbc） |
| opendbc | carcontroller.py | 读 CC_SP.params（aTarget/slopePct）+ 传参 + SnG | ⚠️ CC_SP.params 是 sunnypilot 扩展 |
| opendbc | interface.py | MacanSteerParams 覆盖 steerRatio/friction | ✅ 通用 |
| opendbc | carstate.py | ESP/ACC 状态解析（已在上游 MLB 支持内） | ✅ |
| 主仓 | params_keys.h | 4 个参数注册 | ✅ 通用 |
| 主仓 | controlsd_ext.py | accelerometer 订阅 + slopePct 计算 | ❌ sunnypilot 特有（其他 fork 需适配通道） |
| 主仓 | sunnypilot UI volkswagen.py / mici toggles.py | 开关 | ❌ 按各 fork UI 框架实现 |
| 主仓 | PO 翻译 | 中文条目 | ✅ 通用（直接复制条目） |

### 关键依赖与易错点（本分支实战教训）
1. **slope_pct 必须作参数传入 create_acc_accel_control**——曾误用 CS 变量导致 opendbc 导入 NameError → 整个 openpilot 启动失败（用户 SSH 回退才恢复）
2. 坡度信号链路依赖 sunnypilot 的 CC_SP.params 传参机制——**移植到 dragonpilot/carrotpilot/iqpilot 时**：若没有 CC_SP.params，需改用其他通道（如 cereal 消息扩展 / Params / direct 传递），否则坡度补偿无法工作
3. 每改一个驾驶逻辑文件：**py_compile 语法检查 → 仿真回归 → 实车路试**（开关默认关，开一版试一版）
4. 声称“已推送”前必须 git log 核实（本分支曾多次编造 commit）
5. UI 联动可见性用**整行级 set_visible**（ListItem 渲染检查 self.is_visible；action_item.set_visible 只藏控件）
6. UI 改动后需要真正重启 UI 进程（`restart_service ui`；restart_ui 信号对 sunnypilot UI 无效）

### 数据与工具链（ai/tools/）
`fit_imu_slope_v49.py`（IMU 坡度标定）、`verify_slope_v2.py`（静止/动态验证）、`slope_comp_sim.py`（超载仿真）、`calc_steer_v7.py`（多 route 交叉标定）、`scan_steer_sources.py`（信号源普查）、`scan_slope_route.py`

## 7. 数据可靠性结论（2026-08-19 验算，移植时可引用）

- 坡度信号 ✅ 有效（静止中位 -0.11%）；超载仿真 ✅（上坡超 500 仅 0.0%、下坡 97% 触发）
- 转向标定 ⚠️ 实验值（steerRatio≈18.0 不可靠，默认关等路试）——**移植时勿把这些实验值当最终值**
- 重力向量：中间产物观感异常（设备竖装 ax≈9.587、旧 verify 脚本误算 -1447%）但**差值法 n·acc-s_ref 有效**（安装角被 s_ref 消掉）——坡度计算不受设备安装角影响

## 待办
1. 路试验证坡度补偿实际效果（开关默认关，开一版试一版；我可通过 Params 读开关状态对应 route）
2. 转向标定等更多高速弯数据再修正（18.0/0.52 为实验值）
3. 重力向量可选优化降噪（±1% 噪声不影响当前触发阈值）
4. webui（PC 网页版）104 个 label 硬编码英文待处理（独立 UI，需前端 i18n 表）
