# Macan 仪表显示复核：地库静止无前车 + ACC_Display_Prio 现状（2026-10-04）

> 触发：用户实测 2026-10-04 12:0x 地库 route `00000090--a09d96f03f`（**旧逻辑**：2.A 提交
> `23ede5ab`/opendbc `cd2d457cc` 时间戳 19:52，晚于该次行车），问三件事：
> ① 我改了什么；② bus128 上 `ACC_02.Abstandsindex` 是不是仪表前车距离信号、改前改后差多少；
> ③ `ACC_02.Display_Prio` 是干什么的；④ 为什么地库静止车辆没切视觉。
> 结论先给：**地库段不是"没切视觉"，而是视觉/融合这条源当时也没有目标**（模型 lead 头
> prob≈0.10，radard 门槛 0.5），且 2.A 改动在这条 route 上**逐帧等价（0 帧差异）**。

## 一、bus128 是什么；它上面的 Abstandsindex = OP 实发值（逐帧校验）

- panda 总线编号约定（`panda/board/drivers/can_common.h:124`）：
  `Bit 7 marks message as receipt (bus 129 is receipt for bus 1)` → **bus 128 = bus 0 的"收条"
  （我们自己发出去的回读）**，bus 2 = 原厂雷达域（D4C7 网关源）。
- 验证：route 90 全 6 段，把 bus128 上的 `ACC_02` 与 OP 实际发出的报文（`send`+`can` 事件, src=0）
  逐帧比对：**4985/4985 帧数值完全相同**。→ 用户看到的"bus128 有信号"就是本改动这条路径发出的信号。
- route 90 seg0 的 780 计数：`(2,780)=1531`（原厂雷达域）、`(128,780)=824`（OP 发出收条）、
  `(0,780)=296`（车端自己在 bus0 上的镜像）。

## 二、修改前后对比（route 90：原厂 idx 全程 = 0）

用真实 CarController 回放（`_probe_macan_2a_check.py`），旧=原厂透传+迟滞+2s hold，
新=2.A（只用 `CS.op_lead_dRel` = `radarState.leadOne.dRel`）：

| seg | frames | 原厂 idx>0 | leadOne.present | 日志发出 idx>0 | 旧>0 | 新>0 | **旧≠新** | 日志==旧 | 日志==新 |
|---|---|---|---|---|---|---|---|---|---|
| 0 (地库静止, vEgo≡0) | 825 | 0 | 0 | 0 | 0 | 0 | 0 | 825 | 825 |
| 1 (vEgo≤2.1) | 1000 | 0 | 3 | 3 | 3 | 3 | 0 | 1000 | 1000 |
| 2 (vEgo≤7.6) | 999 | 0 | 30 | 30 | 30 | 30 | 0 | 999 | 999 |
| 3 (vEgo≤5.1) | 1000 | 0 | 121 | 121 | 121 | 121 | 0 | 1000 | 1000 |
| 4 (vEgo≤0.5) | 1001 | 0 | 0 | 0 | 0 | 0 | 0 | 1001 | 1001 |
| 5 (vEgo≤0.4) | 164 | 0 | 0 | 0 | 0 | 0 | 0 | 164 | 164 |
| **合计** | **4989** | **0** | **154** | **154** | **154** | **154** | **0** | **4989** | **4989** |

- **原厂（bus2/src2）`ACC_Abstandsindex` 在 route 90 全程 = 0**（用户的推测正确：无效态）。
- OP 发出 idx>0 的帧数 == `leadOne.present` 帧数（154），**逐帧一致**→"仪表有前车"与"控制链有 lead"
  在这条 route 上本来就已经同源。
- 旧逻辑与新逻辑 **0 帧差异**，且都与日志实发值 100% 吻合 → 原厂 idx=0 时旧逻辑本来就在走
  "融合/视觉补位"分支，**2.A 在这条 route 上是等价改动**（差异只在"原厂 idx 有效但与控制不一致"
  的场景，见下节 8f 反例）。

## 三、对照：有"原厂 idx 有效"的路段（route 8f, 10-03）

同一工具跑 `0000008f--d8503b05a8`（6 段，5786 帧）：原厂 idx>0 = 164 帧（全在 seg4），
`leadOne.present` = 602，日志发出 idx>0 = 615；**旧≠新 = 168 帧**（seg4：13 帧"旧有车→新无车"
+ 155 帧数值改为控制口径），`日志==旧` = 5785/5786（回放口径可靠），`日志==新` = 5617。
即：**只有 seg4 这种"原厂 idx 有效"的路段，2.A 才真正改变仪表行为**，方向一律是把显示拉回控制侧。

## 四、为什么地库静止车辆没有"切到视觉"（两层原因，都不是显示源逻辑）

1. **radard 的门槛**（`selfdrive/controls/radard.py::get_lead`）：只有
   `lead_prob`（`modelV2.leadsV3[0].prob` 经非对称滤波：涨立即、落 0.2s）`> 0.5` 才发布 lead；
   `radarTracks` 有 track 时还要 `ready`。
   route 90 seg0 实测（`_probe_model_lead_prob.py`）：1068 帧里 max prob = **0.10（1067 帧）/ 0.18（1 帧）**
   → 模型自己就没给出"有前车"，radard 不发布 `leadOne` → `op_lead_dRel = 0` → 仪表无可显示目标。
2. **原厂雷达这条源同样为空**：bus2 的 `ACC_Abstandsindex` 全程 0，且 `radarTracks` 点数
   **991/991 帧 = 0 点**（本 build 的原厂雷达点云没有产出 track）→ upstream 的
   `potential_low_speed_lead`（|yRel|<1.0, vEgo<4, 0.75<dRel<25）也没有输入可用。
3. 另有结构性约束：`radard._macan_fuse_leads` 只对**已存在**的 lead 做修正
   （`if not lead.present: continue`），**不能凭原厂 idx 凭空造 lead**。所以"原厂 idx 无效就切视觉"
   这个说法只在"视觉已经给出 lead"时才成立；视觉没给，则两源皆空。

→ 因此旧逻辑、2.A、以及任何显示层改动，在这段都不会让仪表出现前车。要静态/低速也能显示前车，
需要动**感知/跟踪层**（不在 2.A 范围）。

## 五、`ACC_02.Display_Prio` 是什么（现状：仍透传原厂）

- DBC：`vw_mlb.dbc` `ACC_02`(0x30C) → `SG_ ACC_Display_Prio : 44|2@1+ [0|3]`，接收方 `Vector__XXX`
  （未声明 ECU）→ 是给**仪表/显示 ECU 的"显示优先级"选择位**，**不携带距离或"有没有车"信息**。
  仪表画不画前车、画多远，取决于 `ACC_Abstandsindex`(24|10) + `ACC_Relevantes_Objekt`(46|2) 这一对，
  这两个量 2.A 已经统一到控制源。
- OP 行为：Macan 路径**透传原厂** `stock_display_prio`（carstate.py 2026-08-22 决定：重算/默认 0
  与原厂不一致会造成 `ACC_02` 状态矛盾 → 原厂自检 st=6）；只有在"纯 OP 模式"
  (`create_acc_hud_control_pure_op`) 才自算 = `2 if 有目标 else 3`。
- 经验统计（route 90+8f，`_probe_acc02_prio.py` / `_probe_prio_corr.py` / `_probe_acc02_timeline.py`）：
  - 无目标时绝大多数=3（14039 帧），但也有=2 的帧（791+217+144+104…）；
  - 有有效目标（rel=1, ab>0）时 2/3 都会出现，判别量是**车距在收窄还是拉大**：
    `d(ab)≤0`（收窄/保持）→ prio=2（52+37 帧，只有 7 帧例外）；
    `d(ab)>0`（拉开）→ prio=3（137 帧，11 帧例外）。
  - 与 `ACC_05` 的减速请求/力矩、`Status_Anzeige` 无干净相关（其它显示位 hinw/zlAnzeige/tacho 恒 0）。
- **残余不一致（已知，未动）**：因为 Prio 仍是原厂口径，会出现 `Abstandsindex=0 / Relevantes_Objekt=0`
  （OP 说"无目标"）而 `Display_Prio=2` 的帧（上面 791+217+144+104 帧即此类）。若要把显示域也做成
  严格同源，就得改成 `2 if lead_object else 3` —— 但这正是 2026-08-22 判定的 st=6 风险点，
  属 2.A 文档 §5 的残余项，需单独评估（先回放看差异帧数 + 实车只看不动）。

## 六、控制侧对照（回答"仪表没车 ⇒ OP 不刹停/不减速吗"）

- 2.A 之后：显示源 `CS.op_lead_dRel` ←→ 控制源 `radarState.leadOne.dRel` **是同一个对象**
  （`card.py:374` 注入；`long_mpc.py:378` `process_lead(radarstate.leadOne)`）。
  MPC 的前车障碍只来自 `radarState.leadOne/leadTwo`（代码注释："The MPC source is chosen from the
  real radar leads only"）→ **仪表没显示前车 ⇒ ACC 不会因为前车减速**。
- 但"不减速"≠"什么都不做"：设定速度/vCruise、弯道、CarrotPlanner 注入的虚拟停车障碍
  (`stop_obstacle_distance`，红绿灯/停止线)、以及 e2e 长控
  (`modelV2.action.desiredAcceleration / shouldStop`，experimental) 都可以独立产生减速。

## 七、本次新增工具（ai/tools）

| 工具 | 用途 |
|---|---|
| `_probe_macan_2a_check.py <realdata glob>` | bus128 收条 == 实发值校验 + 旧/新逻辑逐帧对比（§二/§三 的表） |
| `_probe_model_lead_prob.py <rlog\|glob>` | 视觉 lead 头 prob 分布 + `leadOne.present`（§四） |
| `_probe_acc02_prio.py <glob…>` | 原厂 vs OP 代发 `ACC_02` 字段组合直方图（含 Display_Prio） |
| `_probe_acc02_timeline.py <rlog> [win]` | `ACC_02` 逐帧时间线（ab/prio/anz/st/tsk），定位 prio 翻转点 |
| `_probe_prio_corr.py <glob…>` | `Display_Prio` 与 d(ab) 方向 / rel / st 的相关性统计 |

## 八、可选的下一步（待拍板，本次未改代码）

1. **Display_Prio 同源化**：`2 if lead_object else 3`，先 8f/90 回放量化差异帧数，再实车观察 st=6
   （若出现即回退）。风险：2026-08-22 的 st=6 教训。
2. **低速/静止前车可显示**（用户"视觉应该有看到"的诉求）：需在感知/跟踪层加门控放宽或低目标源，
   例如把 `V_EGO_STATIONARY` 的低速 track 通道接到本车可用数据（目前 `radarTracks` 恒 0 点，
   没有输入）。风险最大，需专项。
3. 什么都不改：地库/静止场景维持"两源皆空 ⇒ 仪表无车 ⇒ 无前车控制"，语义上如实。
