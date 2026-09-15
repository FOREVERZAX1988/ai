# Macan 夜间路线扫描 + 纯OP/融合代码体检 (0915夜)

> 日期：2026-09-15 深夜-16 凌晨 ｜ 分支：`macan-long-0915`
> 目的：按用户教的方法扫描本机全部 routes 分类（原厂 ACC vs OP 融合 vs 纯OP），
> 逐个分析 ACC 各状态信号规律，并与当前融合/纯OP代码对比排查 bug。

## 0. 【铁律·用户教的】路线分类方法（务必记住，别再按时间分）
- **不能按上传时间区分**原厂ACC routes 与 路试 OP routes。
- **判定方法（~100% 可靠）**：看 ACC 信号在 **bus2 与 bus128 是否重合**。
  - ACC_02(0x30c) / ACC_04(0x324) / ACC_05(0x10d) 的原始报文，bus2(雷达侧) 与 bus128(OP转发镜像) 字节重合度 ≈100% → **纯原厂 ACC 控制路由**。
  - 重合度显著低 / bus2 出现 OP 自算帧 → **OP 融合纵向控制路由**。
- 本机 0002/0003/0004/0049/0070/0071/0072/0074 全部为**纯原厂 ACC 控制**路由
  （bus2=bus128 重合 100%），无 OP 融合路由、无纯OP路由（纯OP尚未路试）。

### 本机实测重合度（2026-09-15 夜，按 ACC_02 原始字节）
| route | bus2帧 | bus128帧 | 重合 | 判定 |
|-------|--------|----------|------|------|
| 0004--915 | 4532 | 4280 | 100% | 原厂ACC |
| 0002--528 | 4501 | 4501 | 100% | 原厂ACC |
| 0049--ac8 | 4536 | 4349 | 100% | 原厂ACC |
| 0074--ea1 | 4529 | 2845 | 0%(停车段) | 原厂ACC(台架/停车) |

## 1. ACC 信号状态规律（原厂ACC route 0004 全59段 + 0002/0049 实锤）

| 状态 | ACC_05/Status | ACC_02/Anzeige(Prim) | ACC_04/Texte_Zusatzanz | TSK_Status_GRA_ACC_02 |
|------|--------------|----------------------|------------------------|------------------------|
| 关闭(主开关OFF,LS_HS=0) | 0 | 0 | **1** | 0 |
| 待命(LS_HS=1未激活) | 2 | 2 (Prim=0) | 0 / 2 | 0 |
| 激活跟车(st=3) | 3 | 3 (Prim=1) | **8 (主) / 7** | **1** |
| 驾驶员超驰(st=4,踩油门) | 4 | 4 (Prim=0) | **3** | **2** |
| 故障 | 6 | 6 | — | 3 |

### 关键确认（用户问 ACC_04/TEXTE 是否出现过 7）
- 信号本身 **`ACC_04/ACC_Texte` 在所有状态恒 = 0**（不是用户看的 0 2 3 8）。
- 用户看到的 **0 2 3 8 是 `ACC_04/Texte_Zusatzanz`（Zusatzanz 泽附加文本区）**：
  - 待命 st=2 → 0/2
  - 激活 st=3 → **8（主，占比高）也出现过 7**（route 0004 seg7: tz=7 有 240 帧与 8 并存）
  - 超驰 st=4 → 3
- **结论：`Texte_Zusatzanz` 确实出现过数值 7**（激活跟车细分文本），与用户观察的
  "0 2 3 8" 不同——7 存在于激活段。当前纯OP代码 `create_acc_04_control_pure_op`
  用 `{0:1, 2:2, 3:8, 4:3}` 映射**缺 7**（激活段固定发 8）。7 vs 8 均为激活跟车
  显示文本差异，对执行无影响（ACC_04 纯显示件），但想更贴合原厂可在激活段细分。

### 关键确认：TSK 映射表（原厂实测 0004 全段）
**TSK=0 ↔ 关闭(0)/待命(2)；TSK=1 ↔ 激活(3)；TSK=2 ↔ 超驰(4)；TSK=3 ↔ 故障(6)**
→ 与用户 0915 规范、代码 `acc_control_value` 完全吻合。

## 2. 代码体检：融合(开) vs 纯OP(关) 对比

### 2.1 力矩/状态机入口（两者共用 acc_control_value）
- 融合：`acc_control_value(LS_HS, accFaulted, long_active=CC.longActive, gas, stock_st=原厂acc05_stock_status)`
  - 激活域跟随原厂镜像：stock_st∈(3,4)→透传；==6→立即发2；否则 gas?4:3
- 纯OP：`acc_control_value(LS_HS, accFaulted, long_active=CC.longActive, gas, stock_st=None)`
  - 不镜像原厂（雷达停用无 stock），long_active 由 OP 自身 CC.longActive 门控。

### 2.2 【重要收敛点】纯OP 激活判定 = CC.longActive，非显式 TSK 握手
- **当前实现**：纯OP 用 `long_active = CC.longActive and not brake_override` 直接驱动
  st=3。TSK 只在 carstate 用作 `cruiseState.enabled / accFaulted` **被动回读**。
- **TSK 依赖确认（用户担心点）**：carstate `cruiseState.enabled = TSK_Status_GRA_ACC_02
  in (1,2)`，而 OP 的 `CC.longActive = CC.enabled ...`，CC.enabled 又依赖
  cruiseState.enabled（OP 纵向时）→ **纯OP 实为「隐式」依赖 TSK 握手**：OP 发 ACC_05
  st=3 → 引擎 ECU 回 TSK=1 → carstate.enabled=True → longActive 持续。与用户
  期望（LS_HS=1 + SET 上升沿 → 发 st → 观 TSK 1/2 确认）**路径一致但未做成显式状态机**。
- ⚠️ **待路试验证**：纯OP 发 LS_01 bus2 待命帧（LS_Tip_Setzen 恒 0，不转发 SET 到
  bus2 雷达）。原厂雷达保持待命不激活。引擎 ECU 的 TSK 是否仍会因 ACC_05 st=3 回 1，
  需实车确认——若原厂要求 LS_01 SET 键到达才能 grant，纯OP 需要额外处理。

### 2.3 【新发现·仿真】超驰(st=4)力矩 融合 vs 纯OP 行为差异
用 `create_acc_accel_control` 仿真（activate 5帧 → override 帧）：
- **融合模式** override：`FM=1, mom≈40-56`（力矩照发巡航值，对齐原厂 st=3 力矩）
- **纯OP模式** override：`FM=0, mom=0`（力矩通道关闭）
- **根因**：ACC_05.FM 在 gas_override 时 = `1 if stock_fm else 0`。融合传原厂
  `stock_fm=True`→FM=1；纯OP `pure_op=True` 清空 `stock_fm=False`→FM=0。
- **解读**：纯OP 驾驶员踩油门超驰时**撤力矩交棒给驾驶员**（不与原厂/驾驶员抢扭矩），
  这是合理的纯OP设计（雷达停用无 stock_fm 可跟）。与融合"力矩照发"区别是**特性不是bug**，
  但需留意：纯OP 超驰时若 MPC 仍请求加速，FM=0 会完全忽略——符合"驾驶员接管"语义。

## 3. 用户6问 + 2附加 逐条确认（代码级）

### Q1 驾驶员介入(超驰)时力矩怎么发 / 原厂ACC信号如何跟随
- 融合：超驰 st=4 时 ACC_05.FM=stock_fm(原厂)，mom≈原厂巡航力矩照发（仿真 mom≈40-56）。
  状态由 acc_control_value 镜像 stock_st：stock∈(3,4)→透传。
- 纯OP：超驰时 FM=0、mom=0（pure_op 清空 stock_fm）→ **撤力矩交棒给驾驶员**。
  这是纯OP设计特性（无原厂可跟），非 bug，但语义与融合"力矩照发"不同，需知晓。
- 力矩上升斜坡 8Nm/帧、撤力斜坡 3Nm/帧、超驰斜坡(verz 0.025→1.285→0) 两模式共用。

### Q2 SnG 在纯OP还生效吗
- **纯OP 禁用** SnG/gap_sync（carcontroller line 735 `not self.macan_pure_op`）。
  纯OP雷达停用，代发 RESUME/DIST 会重新激活雷达，故整体关闭。纯OP启停由 OP 自算
  ACC_05 完成（stopping/loes 事件化在纯OP块内，见 carcontroller 纯OP分支）。

### Q3 OP巡航速度与按键设定，纯OP是否已与融合不同
- **是，已不同**。cruise.py `macan_fusion` 为真(融合)时强制 `v_cruise = CS.cruiseState.speed`
  （读原厂 ACC_02.Wunschgeschw，防与原厂分裂）。纯OP(fusion=0)走 `_update_v_cruise_non_pcm`
  ——OP 自己管理步进/设定键，不读原厂巡航速度（原厂雷达待命无激活）。符合用户预期。

### Q4 纯OP 前车距离/前车车速如何判定
- 均来自 **视觉模型 radarState.leadOne**（card.py: op_lead_dRel/vLead = rs.leadOne.dRel/vLead）。
  纯OP雷达停用 → bus2 无有效 Abstandsindex，纯视觉判定。ACC_02 显示 Abstandsindex 由
  op_lead_to_index(视觉dRel) 换算。

### Q5 纵向激活信号如何判定发送
- 当前代码：纯OP `long_active = CC.longActive`（OP内部状态），acc_control_value 据此发
  st=3。TSK 仅作 carstate 被动回读（enabled/accFaulted）。**未做成用户设想的显式
  "LS_HS=1 + SET上升沿 → 发st → 观TSK 1/2 确认"状态机**，但 effect 等价（CC.longActive
  依赖 cruiseState.enabled=TSK∈(1,2)，即隐式 TSK 握手）。
- 各 st 值：关闭0/待命2/激活3/超驰4/故障6，与原厂一致（见 §1 表）。

### Q6 激活后按SET是否置巡航速度
- 融合：读原厂巡航速度，SET 由 OP 转发到 bus2 激活原厂 ACC，原厂回灌巡航速度。
- 纯OP：走 `_update_v_cruise_non_pcm`，SET 按键事件(LS_01/LS_Tip_Setzen →
  ButtonType.setCruise)由 OP 自行置入 vCruise（anchor 到 vEgo）。**存在**，纯OP自管理。

### 附加A 纯OP打开融合视觉是否还融入雷达距离
- **不会**。radard.py `_macan_fusion_enabled` 门控需 `MacanFusionMode=1` 才为真。
  纯OP(MacanFusionMode=0) → `_macan_fusion_on=False` → 纯视觉，雷达距离不参与。
- **"门控机"含义**：即 `_macan_fusion_enabled()`——把 MacanRadarFusion 开关进一步
  用 `MacanFusionMode=1` + `openpilotLongitudinalControl` 门住（AND 门），
  保证纯OP 即使开了 Radar Fusion 开关也退化为纯视觉（雷达已停用无 idx 可融）。

## 4. 仿真/回放结论
- 单元测试：test_macan_mlb 33 passed；volkswagen/tests 37 passed；safety test_volkswagen_mlb
  58 passed。
- 双模式状态机主路径仿真：待命/激活/超驰/停车保持 均合法，无 2→4、6→3 非法跳变。
- route 0004 seg7 回放：融合镜像原厂(st=3/4)，纯OP 恒 st=3(激活域)，非法跳变=0。

## 5. UI 中文（bug #1）排查结论
- 翻译机制：sunnypilot 直接读 .po（multilang.py，无需 .qm）。LanguageSetting=zh-CHS。
- 逐串验证：Fusion标题"融合控制模式 (Macan)"、长描述、radar_fusion、verz_bridge 的
  zh-CHS 翻译**都已存在于 app_zh-CHS.po 且能被 tr() 解析出中文**。
- 结论：翻译数据齐全，若运行中仍显英文，多为**进程启动时缓存**（multilang 单例在导入时
  读 param 并 load po；新增/改动 po 需重启 UI 进程重新加载）。radar_fusion/verz_bridge
  用 tr_noop 定义但字符串已手工入 po，tr() 仍能查到——非 tr_noop 导致不译。
- 建议：若已重启仍英文，检查 UI 进程是否真重启（语言单例缓存），或 mici/tizi 两套 UI
  中用户正看的那套是否都覆盖。
