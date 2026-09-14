# Macan/MLB ACC02·ACC04·ACC05 协同逻辑与 OP 自算规律（0914 汇总）

> 目的：为后续 OP 独立计算（纯 OP 纵向控制/融合模式关）整理 ACC 三报文的协同工作关系与 OP 自算规律。
> 数据来源：原厂 routes 0002/0004/0049（0065）+ OP 代发实现（opendbc `mlbcan.py` / `carcontroller.py` / `carstate.py` / `car/volkswagen/interface.py`）。
> 分支：`macan-long-0914`，opendbc HEAD `c4f8fb68b`。

---

## 0. 三报文总览（角色分工）

| 报文 | 地址/总线 | 频率 | 角色 | 接收方 | 是否影响 ACC 内部闭环 |
|------|-----------|------|------|--------|----------------------|
| **ACC_02** (ACC_HUD) | 0x30c, bus2 | ~16Hz | **纯显示件**（巡航速度/车距档/HUD 状态文本） | HUD_C7 / Kombi_D4 | ❌ 不影响 |
| **ACC_04** (ACC_Text) | 0x324, bus2 | ~16Hz | **原厂雷达状态文本**（目标车速度/Charisma/提示文本） | 仪表/网关 | 保持总线在线，避免超时监测报 ACC 故障 |
| **ACC_05** (ACC_Accel) | 0x10d, bus2 | ~20Hz | **纵向控制请求核心**（Status/Mom/Verz/FM/FV/Loese/Anhalten/axG） | 发动机/变速箱/ESP | ✅ **最终执行通道** |

**核心结论**：
- 三类信号分工：**ACC_05 = 执行（动），ACC_02 = 显示（看），ACC_04 = 提示文本（说）**。
- 执行闭环完全走 ACC_05；ACC_02/04 是"果"的显示/提示投影，不反哺 ACC 内部计算。
- 纯 OP 纵向时，ACC_05 需完全自算（执行自主），ACC_02/04 显示层可用 OP 自算替代（原厂雷达不再发）。

---

## 1. ACC_05：纵向执行核心（自算规律最密集）

### 1.1 Status_ACC 状态机（源头，`acc_control_value`）
```
输入: main_switch_on(L1主开关), acc_faulted, long_active(OP激活), gas_pressed, stock_st(原厂镜像)
0 = 关闭(主开关OFF)     │ acc_faulted → 6(故障)
2 = 待机(ON未激活)      │ long_active → 3/4(激活域)
3 = 激活/跟车稳态        │ 待机域(ON)   → 2
4 = 激活/加速/超驰段     │ OFF          → 0
6 = 故障
```
- **激活域跟随原厂镜像**（方案B/2026-09-01）：`stock_st in (3,4) → 透传；stock_st==6 → 立即发 2`；否则 `gas_pressed?4:3`。
- **铁律**：
  - 待机域**不能发 4**（ECU 把 `2→4 未经过 3` 视为异常跳变）。
  - 激活中踩油门 → 4(Override)，松油门自动回 3（0004-seg7 实锤；乱发会导致 DTC 锁死）。
  - st=6 必须立即跟随退出（原厂 st6 后 100% 回 2，从未回 3）。

### 1.2 FM/FV（扭矩/减速通道使能）—— **互斥切换**
- `Freigabe_Momentenanf (FM)` 与 `Freigabe_Verzanf (FV)` **互斥**：激活/加速 → FM=1,FV=0；减速 → FM=0,FV=1。
- 减速时 FM=0 撤扭矩、FV=1 开制动；巡航 FM=1 发扭矩。
- **自算：OP 按"激活/减速"二态切换 FM/FV，与原厂 brake 状态同步。**

### 1.3 Momentenanforderung (Mom) —— OP 自算（核心力矩）
```
OP 自算: accel>0 → mom = cruise_torque + accel*85  (正)
         减速     → mom*scale(负侧), 阶跃对齐原厂
```
- 原厂跟随（`stock_follow`）：`torque_active and stock_st==3 and not anhalten and (stock_mom<60 or stock_fv)` → 力矩对齐原厂 stock_mom，消除 OP/原厂分歧。
- 闭环验证：`ACC_05.Mom ≈ Motor_01.MO_Mom_o_ex ≈ m_ex ≈ Fwunsch`（请求→执行 1:1 无丢包）。

### 1.4 Verz_anf (Verz) —— 减速请求（自算 + 跟随闸门）
- 减速域：`target_verz = max(accel_eff, -2.2)`（原厂最深 -2.215）。
  - **急刹对齐原厂瞬间跳深**（原厂一帧到位，无 0.07 阶梯）；缓刹 0.07/帧渐进。
- 停车保持（stopping）：镜像原厂力度 **-2.0**（OP 保持 -0.55 vs 原厂 -2.0 会坡道后溜）。
- 关/待机：verz=0.0（原厂 st=0/2/6 全 0；旧 3.01 饱和值是自创占位，ECU 可能判异常）。
- 坡度补偿：上坡斜率补偿 verz 正声明 `≈4.2*sinθ`，上限 1.0；超驰斜坡序列 0.025→+0.18/帧→峰值。
- **融合模式刹车跟随（安全）**：原厂 `stock_anhalten or stock_fv or stock_verz<-0.05` → OP accel 下限跟原厂（原厂刹车无条件遵从）。

### 1.5 ax_Getriebe (axG) —— 变速箱预期加速度提示（自算 + SnG 透传）
```
停车保持/巡航/待机: axG=0.0 (原厂94-98%为0)
减速: 负值 max(-2.016, -0.6-0.08*v*3.6)
起步/加速/超驰无override: 0.01*mom 上限1.3 (提示变速箱接合)
超驰滑行(st=4,松油门,v>18km/h): -0.3 提示降挡
```
- **关键（SnG/st6 相关）**：起步窗口 axG 必须跟足"跟原厂后"的力矩（`_ax_mom=max(_,stock_mom)`），否则变速箱预告与实际力矩不一致 → 误判车没动 → st6。
- 缓爬 0.005/帧；SnG 起步可双闸门透传原厂 axG（保证变速箱接合）。

### 1.6 Loeseanforderung / Anhalten / Betaetigung_EPB —— 启停
- Loese = OP SnG resume/踩油门逻辑；Anhalten = stopping/esp_hold。
- 起步不抢跑：原厂还在刹（stock_verz<-0.05）→ 不提前起步；原厂已放行 + OP 前车可见 → 放行。

### 1.7 ACC_Beeinflussung_ESP —— **透传原厂**（避免 ESP 请求矛盾）
- `stock_esp` 透传，OP 不自算（ESP 干预协调字段，融合模式必须与原厂一致）。

---

## 2. ACC_02：显示报文（HUD）—— 部分透传 + 部分自算

### 2.1 透传原厂（避免状态矛盾 → st6）
| 信号 | 透传源 | 原因 |
|------|--------|------|
| ACC_Status_Anzeige | stock_status_anzeige | 原厂激活=3/故障=6；OP 重算踩油门=4≠原厂3 → 状态矛盾 st6 |
| ACC_Status_Prim_Anz | stock_prim_anz | 原厂 anz=3→prim=1；OP 自算踩油门翻转会矛盾 |
| ACC_Display_Prio | stock_display_prio | 原厂按 ab 判 2/3；OP 按视觉 lead_obj 相反 |
| ACC_Texte_Primaeranz | stock_texte_prim | 原厂故障=1 显示故障文本，OP 默认 0 丢失 |

### 2.2 OP 自算（写回）
| 信号 | 自算 |
|------|------|
| **ACC_Wunschgeschw_02** | `set_speed if <250 else _WUNSCH_NO_DISPLAY(327.04)` — **OP 巡航速度写回仪表**，无效值统一 327.04（对齐 MLB 原厂，非 MQB 327.36） |
| ACC_Gesetzte_Zeitluecke | 镜像原厂 ZL（对应 DIST 键） |
| ACC_Abstandsindex | op_lead 距离换算（B1 单表 idx→距离） |
| ACC_Relevantes_Objekt | lead_object 或 distance → 1 |

---

## 3. ACC_04：提示文本（辅助显示）—— 透传为主 + 映射

### 3.1 透传原厂（关键，防止显示矛盾 st6）
| 信号 | 透传源 |
|------|--------|
| ACC_Texte_Zusatzanz | stock_texte_zusatz（随 st 变 1/2/8/3） |
| ACC_Charisma_Status | stock_charisma_status |
| ACC_Geschw_Zielfahrzeug | stock_lead_speed_kph（无目标满量程 327.36） |

### 3.2 映射（None 时回退）：Texte_Zusatzanz 随 Status_ACC
```
off=0→1 / 待机=2→2 / 激活=3→8 / 超驰=4→3
```
- Charisma 恒定模板 (FahrPr=2, Status=1, Umschaltung=0)。
- **OP 代发 ACC_04 的意义**：屏蔽 bus2→bus0 转发后，由 OP 在 bus0 保持 ACC_04 周期在线，避免网关/仪表超时监测报 ACC 故障。

---

## 4. 协同工作逻辑（三报文联动规律）

1. **同一状态源驱动**：ACC_05.Status_ACC 是统一状态源；ACC_02.Status_Anzeige / PrimAnz、ACC_04.Texte_Zusatzanz 都是它的"投影"，必须同源一致，任一不一致 → 原厂自检 st=6。
2. **执行 → 显示 → 提示 三层链路**（互不依赖）：
   - 执行层（ACC_05 mom/verz/axG/fm/fv）驱动真实车辆动态。
   - 显示层（ACC_02 Wunschgeschw/Abstandsindex）反映 OP 设定与实际执行。
   - 提示层（ACC_04 Texte/Charisma/目标速度）给仪表文本与目标信息。
3. **OP 自算规律总括**：
   - **执行域（ACC_05）OP 已 100% 自主**：Status/Mom/Verz/axG/FM/FV/Loese/Anhalten 全部自算。
   - **协调/显示域依赖原厂透传**：ACC_02 的 Status/PrimAnz/Prio/Texte、ACC_04 的 Texte/Charisma/目标速度、ACC_05 的 ESP/刹车跟随。
   - **透传只在融合模式（原厂 ACC 并存）时有矛盾风险**（st6）。纯 OP 时原厂雷达不再发这些信号，无 st6 矛盾 → OP 可全部用自算替代。

---

## 5. 纯 OP 纵向控制（融合关）前的待办

纯 OP 模式的信号生成**基本已具备**（执行层全自主）。主要待办是把 carcontroller 里依赖 `getattr(CS,'stock_*')` 原厂读取的显示/协调字段（ACC_02 Status/PrimAnz/Prio/Texte、ACC_04 Texte/Charisma/目标速度、ACC_05 ESP/刹车跟随），在融合关模式下切换为 OP 自算。需保证非 MLB 平台不受影响（沿用 0914 mqb/pq 补可选参数的门控模式）。

---

## 6. 参考 routes 与实现位置
- 原厂 routes：`00000002`(67段) / `00000004`(59) / `00000049`(39) / `00000065`(6分钟定时炸弹实测) / `00000015`(激活踩油门DTC) / `00000053`(st6矛盾) / `00000056`(st4早切)。
- 实现：`opendbc/car/volkswagen/mlbcan.py`（create_acc_accel/hud/04_control, acc_control_value）、`carcontroller.py`（ACC 分发、stock_* 跟随闸门、SnG）、`carstate.py`（stock_* 读取、>90 无设定归零）。
- 关联文档：`MLB_MACAN_ACC_LOGIC.md`（原厂位定义全表）、`MLB_MACAN_SIM_REGRESSION_FIX_0914.md`（信号能力盘点/鉴证）、`MLB_MACAN_FUSION_MODE_0914.md`（融合模式）。