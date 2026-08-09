# Macan MK1 (MLB) 原厂 ACC 工作逻辑 — 全链路解析

> 来源：route `00000004--915ebf086f--0..25`（2026-08-09 08:00，26 段约 65 分钟）
> 模式：**原厂 ACC 纵向 + openpilot 横向**（无 ECU 锁死，纯原厂纵向行为）
> 方法：逐帧 rlog 解码（bus2/bus0/bus128 交叉验证）+ DBC(vw_mlb.dbc) 位级解析
> 适用：Porsche Macan MK1 / VW MLB 平台纵向适配、ACC 信号因果判定

---

## 1. 总线拓扑与报文归属（源头判定）

| 总线 | 角色 | 关键报文 |
|------|------|---------|
| bus0 | 动力底盘（PT） | Motor_01(0x80), Kombi_01(0x30b), LS_01(0x10b), ESP_04(0x308) |
| bus1 | 车身舒适 | — |
| bus2 | **驾驶辅助（原厂 ACC 雷达）** | **ACC_02(0x30c), ACC_04(0x324), ACC_05(0x10d), ACC_10(0x117), 0x127** |
| bus128 | OP 代发/转发镜像 | 同批 ACC 报文（**与 bus2 字节 100% 相同 → 纯转发**）；HCA_01(0x126) 仅在此 → **OP 代发横向** |
| bus130 | bus0 镜像 | 同 bus0 |

**关键证据**：bus128 上的 ACC_02/04/05/10 与 bus2 逐字节一致（seg0-7 共 3000/3000 全匹配）→ 本 route 中 OP 未代发任何纵向报文，bus128 是 panda fwd_hook 的转发镜像。HCA_01(0x126) 只出现在 bus128（OP 输出）→ 横向由 OP 控制。

**ACC_01(0x109) 在全部 26 段中不存在** → 确认 Macan 原厂总线无 ACC_01（Q5 车主分支代发 ACC_01 是奥迪需求，Macan 代发即凭空插入）。

## 2. 报文角色：源 / 果 / 执行

### 源头（输入）
- **LS_01 (0x10b, bus0)**：拨杆输入。
  - 主开关=bit12, 取消(AB)=bit13, Limiter=bit15, **SET=bit16**, **速度+=bit17**, 速度-=bit18, RESUME=bit19, 距离调节=bit20|2
  - **Macan 特性：SET 键与速度+同键，按下时 bit16+bit17 同时置位**（奥迪不会；OP 解析时若把 bit17 单独当 accelCruise 事件会误判 → resumeBlocked 假象，见 §5）
- 雷达内部状态（ACC_05.Status / ACC_02.Wunsch 是雷达算出的"果"，不是用户直接输入）

### 果（雷达→ECU 的请求）
- **ACC_05 (0x10d, bus2, ~20Hz) = 纵向控制请求核心**（发给发动机/变速箱/ESP）：

| 信号 | 位 | 实测含义 |
|------|-----|---------|
| Status_ACC | 57\|3 | 0=关闭, 2=待机(主开关ON未激活), 3=激活(巡航/跟车稳态), 4=激活(加速/超车段) |
| Freigabe_Momentenanf (FM) | 12\|1 | 扭矩请求使能（激活时=1；减速时=0） |
| Freigabe_Verzanf (FV) | 13\|1 | 减速请求使能（减速时=1；**与 FM 互斥切换**） |
| Momentenanforderung (Mom) | 16\|10 | 扭矩请求值 0-1021（跟随车速/前车动态调节） |
| zul_Regelabw | 26\|6 ×0.024 | 允许调节偏差（实测恒 0） |
| Verz_anf (Verz) | 32\|11 ×0.005-7.22 | 减速请求 m/s²（减速时 -1 ~ -2.2） |
| Loeseanforderung | 43\|1 | 解除请求 |
| ax_Getriebe (axG) | 48\|9 ×0.024-2.016 | 变速箱加速度请求（减速时=-1） |
| Vorbefuellung_Bremsanlage (VorB) | 47\|1 | **制动预充**（减速时=1，为真实制动做准备） |
| Anhalten | 62\|1 | 停车请求（本 route 未触发） |
| KD_Fehler | 63\|1 | **恒 1 = 正常**（DBC 命名误导，勿当故障） |
| ACC_Getriebestellung_P | 14\|1 | P 挡标志 |
| limitierte_Anfahrdyn | 15\|1 | 起步动态限制 |

- **ACC_02 (0x30c, bus2, ~10Hz) = 显示报文**（→仪表/HUD）：Wunschgeschw(12\|10 ×0.32=设定速度), Prim(22\|2), Abstandsindex(24\|10=距离指数), Zeitluecke(37\|3=时间间隔), Texte_Primaeranz(48\|7), erreicht(55\|1), StatusAnz(61\|3)
- **ACC_04 (0x324, bus2, ~10Hz) = 辅助显示**：Geschw_Zielfahrzeug(40\|10 ×0.32=**目标车速度**, 无目标=327.36), Warnhinweis(35\|1), Texte 等（详见知识库 `vw_mlb_acc04_text_mapping`）
- **ACC_10 (0x117)**：紧急制动/预碰撞（AWV/ANB），非常规控制
- **0x127 (bus2, DBC 未收录)**：雷达环境标记报文，60s 内仅 2 次变化（b1/b2 变化与目标切换相关），非控制核心

### 执行反馈（ECU→总线）
- **Motor_01 (0x80, bus0)**：MO_Mom_o_ex(12\|10)=**外部扭矩请求（≈ACC_05.Mom 同值跟随）**, MO_Mom_m_ex(22\|10)=实际输出扭矩, MO_Mom_Fahrerwunsch(52\|10)=驾驶员请求
  - 稳态巡航实测：ACC_05.Mom ≈ o_ex ≈ m_ex ≈ Fwunsch（**请求→执行 1:1，无丢包**）

## 3. 激活时序（seg6 @412.5s 实测）

```
LS_01: SET=1, +=1（Macan 同键同置位）         ← 唯一源头（用户输入）
  → ACC_02.Wunschgeschw: 327→65 km/h          ← 果：设定速度写入显示
  → ACC_05.Status_ACC: 2→3, FM: 0→1           ← 果：待机→激活+扭矩使能
  → ACC_05.Momentenanforderung: 0→35→116      ← 果：扭矩请求爬升
  → cruiseState.enabled: 0→1, vEgo 61.7→65+   ← 果：整车执行
```

激活前雷达已在持续跟踪前车（ACC_04.ZielV 跟随前车、ACC_02.Abstand 随距离变化）但 Mom=0 无请求 → **雷达感知 ≠ ACC 控制，激活是状态机门控的**。

## 4. 减速切换机制（seg7 @439.9s，核心）

背景：巡航 65km/h，前车靠近（Abstand 327→95，ZielV 69→63）。200ms 内完成模式切换：

```
FM 1→0 + Mom 87→0        ← 先关扭矩通道
FV 0→1 + Verz 0→-1       ← 再开减速通道（互斥）
axG 0→-1                 ← 变速箱减速请求
VorB 0→1                 ← 制动预充（准备液压制动）
→ 发动机 o_ex 88→10（扭矩卸载），vEgo 64.3→61.2
```

**要点**：原厂 ACC 的加速/保持走 **Mom 扭矩请求**，减速走 **Verz/axG 减速请求 + VorB 预充**，两通道通过 FM/FV 互斥切换，绝不混用。**模拟原厂必须复刻这套状态切换**（OP 纵向要同时驱动 FM/FV/Mom/Verz/axG/VorB 的一致性）。

## 5. SET / 取消语义（实测）

- **未激活时按 SET**：Wunsch 重置为**当前车速**（seg12：残留 59 → 33 @32km/h），非恢复上次设定
- **激活后按 SET+**：每次 **+1 km/h**（seg7：65→66→67→68，每次按键）
- 取消（AB 拨杆）：Status→2（待机）、FM→0（实测 seg12）
- **对 OP 的坑**：Macan SET 按下时 bit16+bit17 同置位，OP carstate 若把 bit17 映射为 accelCruise 事件 → selfdrived 视为 resume → vCruise 异常 → UI 提示"Press Set to Engage"（resumeBlocked 假象）。正确做法：SET 优先解释，bit17 仅作速度+处理或忽略同帧的 bit16 冲突。

## 6. 状态机（Status_ACC）

| Status | 显示状态 | 场景 | 特征 |
|--------|---------|------|------|
| 0 | — | 关闭 | seg1 点火初期 |
| 2 | Anz=2 | 待机（主开关 ON，未激活） | FM=0, Mom=0, Wunsch 保留上次值 |
| 3 | Anz=3, Prim=1 | 激活-巡航/跟车稳态 | FM=1, Mom 动态 65-130 |
| 4 | Anz=4, Prim=0 | 激活-加速/超车段 | Mom 升高, o_ex 峰值 149 |

## 7. 已知功能局限（原厂行为，非 bug）

- 不识别/不制动静止目标
- 红绿灯、弯道不减速（无地图感知）
- 低速蠕行（<30km/h）仍可跟车（seg12 Mom 9-43）

## 8. 对 OP 纵向适配的启示（含历史教训）

1. **bus128 = 转发镜像** → OP 完全不碰 ACC_05 时车辆 100% 原厂行为（本 route 证明无冲突）
2. **不要代发 ACC_01**：Macan 原厂无此报文（Q5 fork 教训）
3. **不碰 ACC_04**：之前屏蔽+代发导致 ECU 锁死（历史验证）
4. **代发 ACC_05 需完整模拟**：FM/FV 互斥切换 + Mom/Verz/axG/VorB 同步 + Status 状态机 + counter/checksum（vw_mlb.dbc 有 CRC/checksum 定义）
5. **HCA_01(0x126)** 是 OP 横向代发通道，本 route 全程代发无冲突（原厂 ACC 与 OP LKAS 共存 OK）
6. 发动机请求链路已验证：ACC_05.Mom → Motor_01.o_ex → m_ex → 实际车速（可作 OP 纵向闭环的参照基准）

## 9. 参考路线段

- seg6: 首次激活（SET 65）
- seg7: 全程巡航 + 最强减速（Verz=-2.21）+ SET 逐级 +1
- seg8: 跟车巡航（ZielV 44-54）
- seg9: 多次拨杆调整
- seg12: 低速跟车 + 取消（AB=8）
- seg20: 95km/h 高速巡航 + 减速（Verz=-0.80）
- seg21: 两次启停

## 10. 附：关键位定义速查（vw_mlb.dbc 交叉验证）

- ACC_05 = 269 = 0x10d；ACC_02 = 780 = 0x30c；ACC_04 = 804 = 0x324；ACC_10 = 279 = 0x117；LS_01 = 267 = 0x10b；Motor_01 = 128 = 0x80；HCA_01 = 294 = 0x126
- 所有 ACC 报文含 CHECKSUM(0|8) + COUNTER(8|4)；ACC_05 checksum 算法见 vw_mlb.dbc

---

## 11. ECU 状态回传闭环（TSK 家族，bus1，全部由发动机 Motor_EDC17_D4 发出）

> 用户补充要求：除 ACC 请求链外，ECU 侧状态回显同样重要。本 route 实测（seg7 全程巡航+减速）：

| 报文 | ID | 频率 | 关键信号 | 实测行为（route 00000004） |
|------|-----|------|---------|--------------------------|
| TSK_02 | 0x10c | — | TSK_Status(16\|2) | 本 route 未出现（可能仅点火/特殊状态） |
| TSK_03 | 0x312 | ~20Hz | FAS_Wunschgeschw(12\|10 ×0.32) / FAS_Status_Prim_Anz(22\|2) / FAS_Status_Anzeige(61\|3) | 发动机回显设定速度+显示状态，与 ACC_02 字段同构（HUD/仪表交叉验证） |
| TSK_04 | 0x10e | ~50Hz | **TSK_Status_GRA_ACC_02(62\|2)** | **子状态机回显：1=巡航 2=加速段，与 ACC_05.Status(3/4) 一一对应（421s:ST3/St02=1, 430s:ST4/St02=2）** |
|        |       |      | TSK_ax_Getriebe(18\|9 ×0.024-2.016) / TSK_Wunsch_Uebersetz(27\|10) / TSK_Freig_WU(37\|1) | 本 route 恒 0（常规减速未触发变速箱主动减速/换挡请求） |
| TSK_05 | 0x111 | ~50Hz | **TSK_Status_GRA_ACC_01(16\|2)** | **激活状态回显：0=待机 1=激活，与 cruiseState.enabled 对应** |
|        |       |      | **TSK_Steigung(40\|8 ×0.8-101.6)** | **坡度实时工作（实测 -2~+2%），发动机坡度补偿输入，OP 可直接复用** |
|        |       |      | TSK_Fahrzeugmasse(18\|5 ×200+500) | 本 route=500（无效/未设置） |
|        |       |      | TSK_Freig_Verzoeg_Anf(55\|1) / TSK_Verzoeg_Anf_02(56\|8 ×0.024-3.984) | 本 route 恒 0（需更强减速/跟停场景验证） |
| ESP_01 | 0x100 | ~50Hz | ESP_Verz_TSK_aktiv(27\|1) / ESP_Konsistenz_TSK(29\|1) | 本 route 恒 0（常规滑行减速未触发 ESP 主动制动） |

### TSK 闭环结论（对 OP 适配）
- **状态机回显可用**：ACC_05.Status 3↔4 ↔ TSK_04.St02 1↔2；激活态 ↔ TSK_05.St01=1 → OP 代发 ACC_05 后可用 TSK 回显做闭环验证
- **减速执行路径**：常规减速（Verz -1~-2.2、axG -1~-2）由**发动机扭矩卸载+滑行**完成，TSK_04.ax_Getriebe / TSK_05.Verz02 / ESP_01.VerzTSK 均未置位；液压制动需更紧急场景（待新 route 验证，注意 Anhalten/VorB 联动）
- **坡度补偿**：TSK_05.Steigung 实时可用 → OP 纵向控制可直接读取做坡度补偿
- 注意：TSK 系列在 bus1（发动机域），ACC 系列在 bus2（雷达域），两条域经网关交互

## 12. 总线活跃信号全景（seg1 实测 60s，DBC vw_mlb.dbc）

### bus0（PT 动力底盘，44 个活跃 ID）
- 100Hz：LH_EPS_03(0x9f)、Getriebe_01(0x82)、LWI_01(0x86)、0xa1(未收录)、Motor_01(0x80)、Motor_03(0x105)
- 50Hz：TSK_05(0x111)、ESP_01(0x100)、ESP_02(0x101)、ESP_03(0x103)、Getriebe_03(0x102)、ESP_05(0x106)、ESP_08(0x11e)、EPB_01(0x104)
- 20Hz：Kombi_01(0x30b)、Airbag_01(0x40)、ESP_04(0x308)
- 10Hz：Blinkmodi_01(0x363)、ESP_07_FR(0x392)、LS_01(0x10b)、Klemmen_Status_01(0x3c0)、Gateway_05(0x39c)、Gateway_06(0x39f)、Licht_hinten_01(0x471)、0x3c1/0x3a0/0x3c3(未收录)
- 低频：VIN_01(0x6b4)、BCM(0x526)、Dimmung_01(0x5f0)、PSD_01/02(0x3a1/0x3a2)、Gateway_11(0x644)、Kombi_02/03(0x6b7/0x6b8)

### bus1（舒适/发动机域，70 个活跃 ID）
- 100Hz：0xb0(未收录)、Getriebe_02(0x83)、Motor_02(0x81)、0xaa/0xab(未收录)、LH_EPS_03(0x9f)、LWI_01(0x86)、Motor_03(0x105)、Getriebe_01(0x82)
- 50Hz：TSK_04(0x10e)、TSK_05(0x111)、Motor_04(0x107)、Motor_10(0x114)、LH_EPS_02(0x11d)、ACC_05(0x10d，转发)、ESP_01/02/03(0x100/101/103)、ESP_05(0x106)、ESP_08(0x11e)、Getriebe_03(0x102)、EPB_01(0x104)
- 20Hz：TSK_03(0x312)、Motor_05(0x30e)、BEM_01(0x309)、Kombi_01(0x30b)
- 10Hz：LS_01(0x10b)、Klima_01(0x3bf)、Getriebe_04(0x441)、0x3b2/0x3b3/0x3f1/0x663/0x390(未收录)

### bus2（驾驶辅助/ACC 雷达域，7 个活跃 ID）
- 20Hz：ACC_05(0x10d)、ACC_10(0x117)、0x127(未收录)
- 10Hz：ACC_02(0x30c)、ACC_04(0x324)
- 1Hz：0x395(未收录)、0x6b9(未收录)

### bus128（OP 通道，9 个活跃 ID）
- 镜像：ACC_05/ACC_10/ACC_02/ACC_04/0x127/0x395/0x6b9（与 bus2 一致）
- **OP 代发**：HCA_01(0x126, 20Hz)=横向 LKAS；LDW_02(0x397)=车道偏离输出

### bus130（bus0 转发镜像，44 个活跃 ID，内容与 bus0 相同）

---

## 13. 补充信号：变速箱降挡 / 横向闭环 / 发动机状态 / 未收录报文（seg7 实测）

> 第二轮补充扫描：除 ACC 请求链与 TSK 回显外，对 bus0/bus1 与横向/纵向执行相关的活跃信号做实测验证。

### 13.1 变速箱（Getriebe_03=0x102 bus0 50Hz / Getriebe_01=0x82 bus0 100Hz）— 原厂 ACC 减速的降挡机制

| 信号 | 位 | 实测 |
|------|-----|------|
| GE_Zielgang | Getriebe_03 24\|4 | **目标档位：减速时主动降挡**（449s v55=6挡 → 450.8s=5挡 → 452.2s=4挡） |
| GE_Uefkt | 14\|10 ×0.1 | **实际传动比跟随降挡**：2.90→3.20→3.60→4.10（降挡完成即变） |
| GE_Eingangsdrehz | 48\|14 | 变速箱输入转速（随车速降，降挡后回升） |
| GE_Schaltvorgang | Getriebe_01 12\|1 | **换挡过程标志：整个降挡期间=1** |
| GE_Status_Schaltablauf | 29\|3 | 本车恒 0 |
| GE_MMom_Soll | 16\|10 | 恒 1022（=空闲/无请求，非有效扭矩值） |

**结论**：原厂 ACC 常规减速 = **发动机扭矩卸载（Motor_01.o_ex→低）+ 变速箱主动降挡（Zielgang/Uefkt/Schaltvorgang）** 双执行路径；BEM_Segel_Info 全程 0 → **本车无滑行模式（Segeln）参与**；ESP/EPB 液压制动不参与（见 13.3/13.4）。这是对 §11"减速走发动机卸载+滑行"的**精确修正**：是"卸载+降挡"，不是"卸载+滑行"。

### 13.2 横向闭环（LH_EPS_03=0x9f bus0 100Hz + LWI_01=0x86 bus0 100Hz）— OP LKAS 闭环信号

| 信号 | 位 | 实测 |
|------|-----|------|
| EPS_HCA_Status | LH_EPS_03 32\|4 | **恒 7 = EPS 正在执行 HCA 横向控制请求**（OP 代发 HCA_01 的确认回显） |
| EPS_Lenkmoment | 40\|10 ×1cNm，VZ=55 | 驾驶员/路面扭矩反馈：直行 -5~-30cNm，转向/介入时 -80~-160cNm |
| EPS_DSR_Status | 12\|4 | 恒 3（DSR 状态） |
| LWI_Lenkradwinkel | LWI_01 16\|13 ×0.1，VZ=29 | 方向盘转角（±800°），OP carState 转向角输入源 |
| LWI_Lenkradw_Geschw | 31\|9 ×5 | 转向角速度 |

**结论**：HCA_01(OP 发) → EPS 执行 → LH_EPS_03.EPS_HCA_Status 回显 + EPS_Lenkmoment 驾驶员扭矩（OP 判断介入用）+ LWI_01 角度。**OP 横向适配的完整闭环信号已确认可用**。

### 13.3 制动侧确认（EPB_01=0x104 bus0 50Hz / ESP_01 见 §11）

- EPB_Freig_Verzoeg_Anf(15\|1) / EPB_Verzoeg_Anf(16\|8 ×0.048-7.968)：常规减速**恒 0** → EPB 不参与 ACC 常规减速
- ESP_01.ESP_Verz_TSK_aktiv：恒 0（见 §11）→ 液压制动仅限更紧急场景
- **减速强度分级**（v55→31 场景）：扭矩卸载 + 降挡（0~-2.2m/s²）→ ESP/EPB（待新 route 验证触发阈值）

### 13.4 发动机状态（Motor_03=0x105 bus0 100Hz）

- MO_Drehzahl_01(16\|16 ×0.25)：巡航 1320rpm@6挡，减速降挡后 922→1028rpm（低挡位转速回升）
- MO_Fahrpedalrohwert_01(48\|8 ×0.4)：ACC 控制全程 0（无油门）
- MO_Fahrer_bremst(35\|1)：减速时 0（驾驶员未踩刹车，纯 ACC 执行）
- MO_Motor_laeuft(39\|1)：恒 1

### 13.5 未收录报文身份速查（对 ACC 适配影响：全部无）

| ID | bus | 频率 | 实测特征 | 判定 |
|----|-----|------|---------|------|
| 0xa1 | 0 | 100Hz | 5997 unique/11998 帧，每帧变化（含计数+转速相关字节） | 高动态传感器/状态类，身份未知，不影响 ACC 链路 |
| 0xb0 | 1 | 100Hz | 1013 unique/6000，中动态（byte0-1 变化） | 未知，非 ACC 相关 |
| 0xaa / 0xab | 1 | 100Hz | 16 unique（counter-only，内容恒定） | 心跳/状态类 |
| 0x12b | 1 | 33Hz | 全零 | 无意义 |
| 0x395 | 2 | 10Hz | 540 unique/1200，中动态（byte0/4-5 变化） | 疑似雷达配置/诊断，非控制请求 |
| 0x6b9 | 2 | 1Hz | 全零 | 无意义 |

---

## 14. 跟停（stop & go）与 RESUME 恢复机制（route 00000002--5284e8b7f1 seg13/14 实测）

> 来源：旧 route（本地 seg9-40 共 32 段）。seg13 = 32→0 km/h ACC 跟停；seg14 = 停稳保持 + RESUME 恢复起步。补齐了 §7 中"Anhalten 未触发"与"RES 未按过"的缺口。

### 14.1 跟停过程（seg13，60s 内 32km/h → 0）

| 阶段 | ACC_05 | 其他 |
|------|--------|------|
| 减速中（0-26s） | FV=1、Verz=-1、axG=-1、**VorB=1（制动预充全程保持）**、FM=0、Mom=0 | o_ex≈30（怠速），TSK/ESP/EPB 全 0 |
| **Anhalten 置位（26s，v≈2km/h）** | **Anh=1**，之后持续保持 | — |
| 蠕行逼近（26-58s） | Anh=1 保持，v 2→0 约 30s | — |
| **停稳后（58s+）** | ST=3 保持激活、Anh=1、**Verz 从 -1 加大到 -2**、VorB=1、FM=0/FV=1 | o_ex≈37（怠速维持），ESP_VerzTSK=0、EPB_FreigV=0 |

- **Anhalten 语义**：v≈2km/h 时置位，置位后**持续保持**（不是单帧脉冲）；停稳后 Verz 反而加大到 -2（维持"停住"请求）
- **液压制动不参与常规跟停**（平路）：ESP_VerzTSK/EPB_FreigV 全程 0；停稳保持力 = **1挡怠速拖滞**（变速箱 Zielgang=1、Uefkt=17.2、Waehlhebel=8=D、Eingang=0，发动机不熄火 o_ex≈37）
- **TSK_05.Verz02/FreigV 全程 0（含 Anh=1/Verz=-2 时）**→ 确认 Macan 上 TSK_05 减速回显**不参与** ACC 减速/停车链路（DBC 位定义可能不对应 Macan，勿用于 OP 闭环）

### 14.2 RESUME 恢复起步（seg14 @58.5s，100ms 内完成）

```
停稳保持（0-58s）: ST=3, FM=0, FV=1, Verz=-2, VorB=1, Anh=1, o_ex≈38
58.5s 按 RES（LS_RES=1）
58.6s: FM 0→1, FV 1→0, Mom 0→49→52, Loese=1, VorB 1→0, Anh 1→0
58.7-59s: Mom→69, o_ex 48→59, axG 0→1, 车辆起步
```

- **Loeseanforderung 语义修正**：=「解除保持/起步释放」，不是"取消 ACC"（ST 全程保持 3）——RESUME 起步瞬间置位，伴随 Anh 1→0
- 状态切换再次实锤 **FM/FV 严格互斥**（停住=FM0/FV1，起步=FM1/FV0）
- 与 00000004 seg6（SET 激活）对比：激活/恢复的状态机切换模式一致

### 14.3 对 OP 适配的意义（跟停状态机模板）

代发 ACC_05 的跟停完整状态机：

```
减速:  FV=1, Verz=-1~-2, axG=-1, VorB=1        (FM=0)
置停:  v<2km/h → Anhalten=1 保持               (Verz→-2)
停稳:  ST=3, Anh=1, VorB=1, FM=0/FV=1          持续
起步:  Loese=1 + FM=1 + Mom 爬升 + Anh 0         (RES 或前车起步触发)
```

- 平路跟停**无需模拟 ESP/EPB 液压制动**（原厂不介入）；坡道保持/溜车防护机制未验证（需坡道跟停场景）
- OP 若只发纵向，可读 carState vEgo 判断 v<2km/h 触发 Anhalten，停稳后持续保持直至起步条件

---

## 15. TSK_04.Wunsch_Uebersetz 实测场景补充（route 00000052--a4174c6649，13 段）

> 低速城市场景（seg0-4 人工驾驶、seg5-7 ACC 低速跟车 28-32km/h、seg8-12 静止/蠕行）。该 route 无减速/跟停/坡道事件（verz_min=0、anhalt=0 全程），但揭示了 TSK_04 期望传动比信号的激活场景。

### 15.1 Wunsch_Uebersetz 实测（seg8，v≈8km/h 低速蠕行，ACC 待机 st=2）
- raw(27|10) 分布：**raw=5（=0.12，2130帧/71% 常态）+ 间歇大值（548→13.4、531→13.0、192→4.7、175→4.3 传动比）**
- 对比：00000004/00000002 巡航/跟停时该信号全程 0
- **结论**：Wunsch_Uebersetz 是**低速/换挡过程中的目标传动比通知**（供 ESP/发动机扭矩协调），巡航稳态与 ACC 减速降挡时**不激活**（减速降挡走 Zielgang/Uefkt 机制，见 §13.1）——OP 纵向适配无需关注此信号

### 15.2 低速 ACC 跟车（seg5-7）与既有知识一致
- 28-32km/h 跟车：ST 2↔3↔4、Mom 68-96（加速请求为主）、SET 按键 7 次微调设定速度
- 无减速请求（verz_min=0）——与 00000004 seg12 低速蠕动结论一致，无新增

### 15.3 未覆盖场景提醒（该 route 不满足）
- 急刹/液压制动（ESP_VerzTSK）、跟停（Anhalten）、坡道、RESUME 均未出现
- 剩余待验证项仍为：**急刹触发阈值、坡道跟停保持、下长坡 Uebersetz/降挡行为**
