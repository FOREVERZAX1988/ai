# Macan 仪表车距显示源 = 控制源（2.A，2026-10-04）

> 分支 `sp-macan-re` ｜ 触发：实车发现"仪表前车车距"与融合(视觉+雷达)控制不同源，用户拍板 **2.A**。

## 一、用户决策（原话要点）

- 现象：地库静止车辆场景，原厂 ACC `idx=0`（无效）却没切视觉；怀疑仪表直接复制原厂信号。
- 追问："仪表盘显示源是否跟控制源一致？仪表没显示有前车时，OP 会不会刹车？"
- 结论（用户）：**"仪表跟控制同源，我才能判断摄像头/原厂雷达是否捕捉到前车"** ——
  仪表显车 → 可再等 OP 动作；仪表无车而前方有车 → 立即人工介入。故选 **2.A：显示源 = 控制源**。

## 二、为什么原来不一致（改动前）

三层链路（详见 `MLB_MACAN_ACC_LOGIC.md` §15）：

| 层 | 载体 | 取值 |
|---|---|---|
| 显示层 | OP 代发 `ACC_02.Abstandsindex/Relevantes_Objekt`（bus128→网关镜像） | 原厂 idx 有效 → **透传原厂**；无效 → 视觉补位；30%/20% 迟滞 + 2s hold |
| 控制层 | `radarState.leadOne` → planner → `ACC_05` | radard 融合（`_macan_fuse_leads` A1 速度加权 + A2 距离校验） |

两条链只共用输入、不共用判据，于是产生两类不一致：

1. **仪表有车 / 控制无车**：原厂 idx 有效但 `leadOne.present=False`（route `8f--4` 实测）。
2. **迟滞单向锁**：出现 1 帧「原厂有目标 ∧ 融合缺失」→ 整段锁在原厂 idx，不再回融合。

（另外 2s hold 会让目标消失后仪表再挂 ~2s，属"反向误导"。）

## 三、改动（仅 Macan，车 fingerprint 门控）

`opendbc/car/volkswagen/carcontroller.py`：

- `__init__`：新增 `self.macan_disp_fused = (CP.carFingerprint == "PORSCHE_MACAN_MK1")`
  （异常兜底 False；其他 MLB 如 AUDI_Q5_MK1 恒 False → 走上游原逻辑）。
- HUD 分支拆两条路径：
  - **Macan（2.A）**：`raw_abstand = op_lead_to_index(CS.op_lead_dRel, vEgo)`，
    `lead_object = 1 if raw_abstand > 0 else 0`。**删掉**原厂透传、30%/20% 迟滞、2s hold。
    数据源 `CS.op_lead_dRel` = `radarState.leadOne.dRel`（`card.py:374` 注入）= planner 用的同一对象。
  - **其他 MLB / 上游**：原实现原样保留在 `else:` 内（行为逐帧不变）。
- 保留不变：显示变化率限速 `max_step`、无目标透传 0（防 `ab=0/relev=1` 矛盾帧）、
  `ACC_Wunschgeschw_02` 写回（=OP vCruise）。

## 四、验证

1. **单测** `opendbc.car.volkswagen.tests.test_macan_mlb`：**37 用例全绿**（新增 4 条
   `TestMacanDisplaySourceFused`，驱动**真实 CarController**，`PORSCHE_MACAN_MK1` + `AUDI_Q5_MK1` 双车型）：
   - 显示值 = 控制 lead 反算 idx（原厂 idx=400 / 融合 40 m → 发 186，不再透传 400）
   - 原厂有目标但控制无 lead → 恒 `(0,0)`（旧逻辑发 400）
   - lead 消失**当帧**清零（旧逻辑有 2s hold）
   - Q5 仍为上游行为（偏离>30% → 透传 400；1 帧缺失 → 锁 400）
   - **反证**：把门控关掉（=旧逻辑）同场景发出 400，说明用例确实锁住 2.A 行为。
2. **场景表**（`ai/tools/_probe_macan_disp.py`，20 m/s）：S1 两源一致→398；S2 偏离>30%→**186**（旧=400 锁死）；
   S3 中间 1 帧融合缺失→**该帧 0**、恢复后 398（旧=整段锁 400）；S4 原厂无目标/融合有→398。
3. **全量 route 回放**（`ai/tools/_probe_macan_disp_2a_diff.py`，本地 rlog 10775 帧）：
   | 指标 | 值 |
   |---|---|
   | 旧逻辑复现日志（口径可靠性） | **99.99%** |
   | 新旧完全相同 | 10607 帧（98.4%） |
   | 旧"有车"→新"无车"（=控制侧本就无 lead） | **13 帧** |
   | 两边都有目标但数值不同（原厂 idx → 控制距离） | 155 帧（\|Δ\|均值 30.8 idx） |
   | 旧"无车"→新"有车" | **0 帧** |

   即：只在"原厂说的情况与控制不一致"的 168/10775 帧（1.6%）发生变化，且方向全部是
   "把仪表拉回控制侧口径"（没有新增仪表显示控制不用的目标）。
4. **仿真回归**：`ai/tools/sim_test_macan.py` 5 组全绿；`sim_test_macan_sng.py` 50/50 通过。

## 五、残余项（未做，待拍板）

- `ACC_Display_Prio / Status_Anzeige / Status_Prim_Anz / Texte_Primaeranz` 仍**透传原厂**
  （2026-08-22 为避免 `st=6` 一致性自检刻意为之）。2.A 统一的是"有没有前车 + 车距"两个量
  （`Abstandsindex` + `Relevantes_Objekt`）；若要更严格同源需单独评估 st=6 风险。
- `ACC_Gesetzte_Zeitluecke`（仪表车距**格数**）来自原厂 DIST 键=用户设置，非目标指示，保持透传。
- 地库静止车辆不显示前车属**感知层**（`radard` 门槛 `prob>0.5` / `V_EGO_STATIONARY`），不在本次范围。
- 视觉 lead `|y|` 最大 3.3 m（邻道静车）会成为 `leadOne`：radard 不做车道内过滤，现在会**显示且参与控制**，
  建议单独立项（加 `|y|<1.5` 显示/控制约束）。

## 六、回滚

`self.macan_disp_fused` 置 False（或 revert 本 commit）即回到"原厂优先透传 + 迟滞"旧行为；
其他车型从未受影响。
