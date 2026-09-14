# Macan 0914 仿真回归修复 + ACC02/04/05 信号能力盘点（0914 追加）

> 分支：`macan-long-0914` ｜ opendbc HEAD：`c4f8fb68b` ｜ 主仓库 HEAD：`b57ad404a` ｜ 日期：2026-09-14 追加
> 由「仿真测试上路试」需求触发：首次运行 `test_car_interfaces` 即暴露 **0914 融合模式引入的非 MLB 运行期回归**。

---

## 一、本次核心成果：仿真测试抓到并修复了一个真实回归

### 问题现象
- 运行 `test_car_interfaces.py`（VW/Audi/Porsche 全 24 车型接口仿真）时，**全部非 MLB VW/Audi 车型（24 个中的 20 个，如 GOLF_MK7、SHARAN、AUDI_A3_MK3、Q3_MK2 等）崩溃**：`TypeError: acc_control_value() takes from 3 to 4 positional arguments but 5 were given`，随后还有 `create_acc_accel_control() got an unexpected keyword argument 'stock_verz'` 等连环报错。
- **根因**：`carcontroller.py` 在共享的 `if self.CP.openpilotLongitudinalControl:` 块内，**无条件**调用 `self.CCS.create_acc_*/acc_control_value` 并传入 Macan(MLB) 专属的 kwargs/位置参数：
  - `acc_control_value(..., stock_st)`（第 5 参）
  - `create_acc_accel_control(..., stock_verz, verz_follow, bridge_ttc, axg_comp, stock_axg, stock_fm, stock_anhalten, slope_pct, slope_comp, slope_comp_unlimited, sng_resume_req, lead_distance, lead_speed)`
  - `create_acc_hud_control(..., stock_prim_anz, stock_status_anzeige, stock_texte_prim, stock_display_prio, stock_wunschgeschw)`
  - `create_acc_04_control(..., stock_texte_zusatz, stock_charisma_status)`
- **只有 `mlbcan.py`（Macan/MLB）的这四个函数接受这些参数**；`mqbcan.py`/`pqcan.py`（MQB/PQ）签名不匹配 → 运行时 TypeError。

### 违反的硬性要求
用户曾明确要求：**所有改动仅 Macan/MLB 生效，其他车型不受影响**。此回归使全部非 MLB VW/Audi 车型在 OP 纵向开启时崩溃，直接违背该要求。

### 修复方案（纯增量，已推送）
- 在 `mqbcan.py`、`pqcan.py` 的四个函数签名上**补齐 Macan 专属可选参数**（默认值与 MLB 相同）：
  - `acc_control_value(..., stock_st=None)`
  - `create_acc_accel_control(..., stock_verz=0.0, verz_follow=False, axg_comp=False, stock_axg=0.0, stock_fm=False, stock_anhalten=False, slope_pct=0.0, slope_comp=False, slope_comp_unlimited=False, sng_resume_req=False, lead_distance=999.0, lead_speed=0.0, bridge_ttc=False)`
  - `create_acc_hud_control(..., stock_prim_anz=0, stock_status_anzeige=None, stock_texte_prim=0, stock_display_prio=None, stock_wunschgeschw=None)`
  - `create_acc_04_control(..., stock_texte_zusatz=None, stock_charisma_status=None)`
- 这些参数在 MQB/PQ 上**被忽略**，行为**逐字节不变**（不改变非 MLB 输出）。Macan 已推送的 `mlbcan.py` 无需改动。

### 验证
- `test_car_interfaces.py`：VW 19 + AUDI/PORSCHE 5 = **24 全绿**（修复前 20 失败）。
- `py_compile` 全通过。
- 已推送：opendbc `c4f8fb68b`（`73f15ddc5a..c4f8fb68b5`），主仓库 `b57ad404a`（bump 子模块指针，`9b42c50ec..b57ad404a`）。
- ✅ 仿真测试**确实有效**——抓到了真 bug，不是空跑。

---

## 二、ACC02 / ACC04 / ACC05 信号盘点（为纯 OP 纵向控制做准备）

> 用户问题：ACC02/04/05 分别是什么？哪些信号 OP 能自己生成？哪些还依赖复制 bus2 原厂 ACC 信号代发？

### 1. 三个报文的角色

| 报文 | 地址/总线 | 频率 | 角色 |
|------|-----------|------|------|
| **ACC_02** (ACC_HUD) | 0x30c, bus2 | ~16Hz | 仪表/抬头显示**纯显示件**（Wunschgeschw 巡航速度、车距档位、HUD 状态文本）。接收方 HUD_C7/Kombi_D4，不影响原厂 ACC 内部闭环。 |
| **ACC_04** (ACC_Text) | 0x324, bus2 | ~16Hz | 原厂雷达**状态文本**报文（T exte/Charisma/目标车速度显示）。OP 代发保持总线在线，避免网关对 ACC_04 超时监测报 ACC 故障。 |
| **ACC_05** (ACC_Accel) | 0x10d, bus2 | ~20Hz | **纵向控制请求核心**（发给发动机/变速箱/ESP）：Status_ACC、Mom(力矩)、Verz(减速)、FM/FV(通道使能)、Loese/Anhalten(起步/停车)等。**纯 OP 纵向的最终执行通道**。 |

### 2. 信号能力：OP 自生成 vs 复制原厂代发

按「当前代发实现是否依赖从 bus2 读原厂值」分类：

#### ✅ OP 已能完全自生成（不依赖原厂）

| 信号 | 所在报文 | 源 |
|------|---------|-----|
| **ACC_Momentenanforderung (Mom)** | ACC_05 | OP 自算：`cruise_torque + accel*85`（正）/ `*scale`（负），标定自原厂实测 |
| **ACC_Verz_anf (Verz)** | ACC_05 | OP 自算（MPC accel → verz），经 MacanVerzBridge 柔化 |
| **ACC_Status_ACC** | ACC_05 | OP 自算（acc_control_value），融合模式透传原厂 st 镜像 |
| **ACC_Freigabe_Momentenanf / Verzanf (FM/FV)** | ACC_05 | OP 自算（激活/刹车通道），融合模式透传原厂 |
| **ACC_Loeseanforderung** | ACC_05 | OP 自算（SnG resume/踩油门逻辑） |
| **ACC_Anhalten / Betaetigung_EPB** | ACC_05 | OP 自算（stopping/esp_hold） |
| **ACC_ax_Getriebe** | ACC_05 | OP 自算（变速箱预期加速度拟合） |
| **ACC_StartStopp_Info / KD_Fehler** | ACC_05 | OP 恒置（1/1） |
| **ACC_Wunschgeschw_02** | ACC_02 | OP 写回（`set_speed`=OP vCruise，无效值统一 327.04） |
| **ACC_Gesetzte_Zeitluecke** | ACC_02 | OP/车距键 |
| **ACC_Abstandsindex / Relevantes_Objekt** | ACC_02 | OP 自算（op_lead_to_index 距离换算，B1 单表） |

#### 🔁 依赖复制 bus2 原厂 ACC 信号代发（当前未做到纯 OP）

| 信号 | 所在报文 | 现状 |
|------|---------|------|
| **ACC_Status_Anzeige** | ACC_02 | 融合模式**透传原厂**（`stock_status_anzeige`），避免状态矛盾 st=6 |
| **ACC_Status_Prim_Anz** | ACC_02 | 透传原厂（`stock_prim_anz`） |
| **ACC_Display_Prio** | ACC_02 | 透传原厂（`stock_display_prio`，原厂按 ab 判 2/3） |
| **ACC_Texte_Primaeranz** | ACC_02 | 透传原厂（`stock_texte_prim`） |
| **ACC_Texte_Zusatzanz** | ACC_04 | 透传原厂（`stock_acc04_texte_zusatz`，随 st 变 1/2/8/3） |
| **ACC_Charisma_Status** | ACC_04 | 透传原厂（`stock_acc04_charisma_status`） |
| **ACC_Geschw_Zielfahrzeug** | ACC_04 | 透传原厂（`stock_lead_speed_kph`） |
| **ACC_Zielobjekt / Charisma_FahrPr/etc** | ACC_04 | 部分透传原厂 |
| **ACC_Beeinflussung_ESP** | ACC_05 | 透传原厂（`stock_esp`，避免 ESP 请求矛盾） |
| **ACC_Anhalten / Verz 跟随** | ACC_05 | 原厂刹车跟随（`stock_verz`/`stock_anhalten`/`stock_fv`/`stock_fm`） |

### 3. 对纯 OP 纵向控制（融合关）的意义

- **执行层（ACC_05 的力矩/减速/通道）OP 已 100% 自主**，不依赖原厂也能发车。
- **依赖原厂复制的集中在「HUD 显示状态」与「协调字段」**（ACC_02 的 Status/PrimAnz/Prio/Texte、ACC_04 的 Texte/Charisma/目标速度、ACC_05 的 ESP/刹车跟随）。
  - 其中大多**只有在与原厂 ACC 并存时才有矛盾风险**（st=6 自检锁死）。
  - **纯 OP（激活时不激活原厂 ACC 雷达）时，原厂雷达不再发这些信号**，也**不会有 st=6 矛盾**——OP 完全可以用自己的重算逻辑替代这些透传，甚至可以直接按「OP 正常模板」生成（OP 已是唯一发件方）。
- **结论**：纯 OP 纵向控制的信号生成**基本已具备**（执行层全自主 + 显示层可用 OP 自算替代透传）。主要待办是把 carcontroller 里「依赖 getattr(CS,'stock_*') 原厂读取」的显示/协调字段，在融合关模式下切换为 OP 自算，并保证非 MLB 平台不受影响（沿用本次 mqb/pq 补齐参数的门控模式）。

---

## 三、HCAMitigation（6 秒 / 6 分钟定时炸弹）验证结论

用户问题：macan 的「6 分钟定时炸弹」和「6 秒」两个问题都修复并起作用了吗？

- **6 秒问题** = EPS 限制**同一扭矩连续输出 ≤6 秒**（`STEER_TIME_STUCK_TORQUE = 1.9`：每 1.9s 若扭矩未变则扰动一次，分 3 次重置覆盖 6 秒窗口）。
  - 实现于 `carcontroller.py` `hca_frame_same_torque` 逻辑：`apply_torque -= (1,-1)` 微扰后清零计数。
  - **已修复且活跃**（对 MLB 平台同样生效，Macan 属 MLB）。
- **6 分钟问题** = EPS 限制**连续转向请求 ≤360 秒**（`STEER_TIME_MAX=360`，开→6 分钟）。
  - 实现于 `eps_timer_workaround`（`bool(CP.flags & VolkswagenFlags.MLB)` 开启，**Macan 命中**）：
    - `STEER_TIME_BM = 240`（240s 开始尝试重置）
    - `STEER_TIME_ALERT = 350`（350s 若未成功 → EPS 软降级警报）
    - 在低扭矩窗口临时 `hca_enabled=False` 让计时器复位，需 `STEER_TIME_RESET=1.1s` 持续 HCA 关闭才有效；MLB 需 >1s 复位。
  - **已修复且对 Macan 生效**。
- 两者是**两个不同机制**，均已由 VW 官方 openpilot 移植逻辑覆盖并确认对 MLB/Macan 激活：`eps_timer_workaround = True`（MLB 标志）。
- 注：这两个是**横向 EPS 转向**的定时炸弹，与纵向 ACC 无关。纵向 0914 改动未触碰该逻辑。

---

## 四、carstate >90 归零限制（用户第 3 问）

- 位置：`carstate.py` MLB 块 `if ret.cruiseState.speed > 90: ret.cruiseState.speed = 0`
- **单位是 m/s**（90 m/s = 324 km/h），用户确认无误。
- **含义**：`cruiseState.speed` 由 `ACC_Wunschgeschw_02(kph) * KPH_TO_MS` 得到；当无有效设定时原厂发 327.04/327.36 kph → 换算后 > 90 m/s → 置 0 =「无设定」。**本质是无设定哨兵识别**，不是「限速 90」。
- git blame 显示该行来自上游移植基线（2026-08-18），**不是防路试加的临时限制**——它是把无设定哨兵清零的规范实现（与 MQB/MEB 的 `>70` / `>90` 同类）。

---

## 五、Wunschgeschw 无效值 327.04 vs 327.36（用户发现）

- 原厂 MLB Macan `Wunschgeschw` 无效值 = **327.04**（raw 1022，"keine Anzeige" 无显示），**不是** MQB/MEB 常看到的 327.36（raw 1023）。
- 差值 **0.32** = 一位 raw 步进（0.32 kph/step）——是**不同 raw 值**，不是信号衰减。
- ✅ **已对齐**（0914 已推送）：`mlbcan.create_acc_hud_control` 用 `_WUNSCH_NO_DISPLAY = 327.04` 封装无显示哨兵（opendbc `73f15ddc`，本次仿真修复前已含）。OP 写回与 carstate 识别两端一致用 327.04。
- 用户提出「与主仓库一起推送」已完成——本次又把 opendbc 37345 后修复推了 `c4f8fb68b`，主仓同步 bump。

---