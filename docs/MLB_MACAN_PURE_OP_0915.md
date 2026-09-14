# Macan 纯OP纵向控制 + 融合切换 (0915)

> 分支：`macan-long-0915` ｜ 关联：`MLB_MACAN_FUSION_MODE_0914.md` / `MLB_MACAN_ACC_SIGNAL_SYNERGY_0914.md`
> 目的：实现 `MacanFusionMode` 开关，ON=融合(原厂雷达+OP纵向, 原逻辑)，OFF=纯OP纵向(雷达停用, OP自算ACC02/04/05)。

## 一、用户需求与实现对照

### 1. 块级 if/else（非逐信号）
用户要求：修改 `mlbcan.py` 时在文件内写块级 `If 融合开关关{完整OP自算...} else {完整OP融合...}`，
而非每个信号单独判断。
- **carcontroller.py**：`if self.macan_pure_op: ... else: <融合原逻辑(仅缩进, 字节级一致)>`。
  - 纵向(ACC_05)与 HUD(ACC_02/04)两块均按此分支。
  - 已用脚本验证：融合块的 accel(175行) 与 HUD(84行) 内容与改动前完全一致（仅 +2 空格缩进）。

### 2. 雷达融合开关联动
- `MacanRadarFusion`（雷达时距/前车速度提供视觉辅助）现需同时 `MacanFusionMode=1` 才生效
  （radard.py `_macan_fusion_enabled` 加 `MacanFusionMode` 门控）。
- `MacanRadarFusion` ON(且融合ON)：雷达 idx 参与视觉共同判断（A1 速度加权 + A2 距离校验）。
- OFF(或纯OP)：纯视觉判定。
- 纯OP模式 bus2 无有效雷达目标（雷达待命），纯视觉。

### 3. LS_01 处理
- 用户澄清：LS_01 待命恒1 是对 **bus2 上的雷达信号**，不是 LS_01 所有信号。
- LS_01 源在 bus1（物理拨杆），网关复制到 bus0 与 bus2。
- 实现：纯OP模式 **不复制物理拨杆按键到 bus2**（避免激活原厂雷达），而是在 bus2(OP代发 CAN.ext)
  只发 **LS_01 待命帧（LS_Hauptschalter=1, 全部按键清0）**，让雷达保持待命不激活。
- bus0/bus1 的 LS_01 照常（驾驶员仍可拨杆设定 OP 巡航速度）。
- 按用户要求：本轮**不做自定义按键发送**（仅保持现状：融合模式复制物理拨杆，纯OP发待命）。

### 4. ACC02 显示
- 纯OP模式 ACC_02 不再纯透传（雷达停用无原厂流），而是 **OP 自算**：
  Status/PrimAnz/Prio/Texte 由 OP 状态派生；Wunschgeschw=OP vCruise；Abstandsindex=视觉换算
  距离（若 MacanRadarFusion 开且融合ON 则用雷达 idx 补强）。
- 距离判定与雷达融合开关协同（见上）。

### 5. safety 不改
- 纯OP纵向的 LS_01 bus2 待命帧（按键清0）能通过现有 `volkswagen_mlb_tx_hook`（仅在
  !controls_allowed 时拦 bit16/bit19，待命帧二者为0）——无需改 safety。
- `test_volkswagen_mlb.py` 全部通过。

## 二、改动文件
- `opendbc/car/volkswagen/mlbcan.py`：
  - 新增 `create_ls01_standby_control`（LS_01 bus2 待命帧）
  - 新增 `create_acc_hud_control_pure_op` / `create_acc_04_control_pure_op`（纯OP ACC02/04 自算）
  - `create_acc_accel_control` 加 `pure_op` 参数：置空所有 stock_* 跟随/透传分支。
- `opendbc/car/volkswagen/carcontroller.py`：
  - `__init__` 读 `MacanFusionMode`/`MacanRadarFusion`，派生 `macan_fusion_on` / `macan_pure_op` / `macan_radar_fusion`。
  - MLB 纵向块：`if macan_pure_op`(自算) / `else`(融合原逻辑)。
  - MLB HUD 块：同上。
  - SnG/gap_sync（给原厂雷达的 LS_01 按键帧）仅融合模式；纯OP禁用。
  - LS_01 bus2：纯OP发待命，融合复制物理拨杆。
- `openpilot/selfdrive/controls/radard.py`：MacanRadarFusion 门控加 `MacanFusionMode`。
- `openpilot/selfdrive/ui/...`：解锁 Fusion Control Mode 开关（纯OP已实现，可自由切换）。

## 三、测试
- `opendbc/car/volkswagen/tests/test_volkswagen.py`：4 passed, 96 subtests。
- `opendbc/safety/tests/test_volkswagen_mlb.py`：58 passed, 74 skipped, 40 subtests。
- 完整 `opendbc/car/volkswagen/tests/`：29 passed, 96 subtests。

## 四、本机 routes 扫描结论（2026-09-15 夜间）

> 用户要求扫描本机全部 routes：按"bus2 与 bus0/bus128 是否重合"区分原厂 ACC vs OP 融合路由；
> 分析 ACC 各状态（关/待命/激活）信号规律；标注潜在 bug。

### 4.1 分类（bus2 vs bus128 重合法）
对所有 8 个 session（00000002/03/04/49/70/71/72/74 = 269 段）抽样 ACC_02(raw Wunsch,Status) 与 ACC_05 Status：
- **全部 route 均 100% bus2=bus128 重合**（ACC_02 重合度 100%）→ 全部为本机 **原厂 ACC 控制** 路由。
- ACC_05 Status 恒为 **0**（待命/关闭），未发现 st∈(2,3,4) 激活段 → 本机 routes 均为停车巡检/台架
  捕获，**无真实路试激活段**。纯 OP 纵向路由尚不存在（与用户"纯OP还没路试"一致）。

### 4.2 ACC 信号状态规律（本机 stock 路由）
- **关/待命（st=0）**：bus2 仍持续发 ACC_02/04/05（Status=0），**Abstandsindex(距离)/ZielV(前车速度)
  持续发送**（验证用户猜想：基础信息信号雷达持续发）。Wunschgeschw 保留上次设定值（~82-312 km/h），
  **未出现 327.04/327.36 哨兵**——点火初始化段 Wunsch raw≈960-975（≈307-312 km/h）。
- **代码 `_WUNSCH_NO_DISPLAY=327.04` 为纯显示件安全值**（DBC VAL 语义 1022 keine Anzeige），
  与 stock 路由的"保留上次值"不冲突（OP 自算显示时用 327.04 表示"无设定"仅供仪表清空，零执行风险）。
- 结论：纯OP模式 ACC02/04 保持 st=0 时仍发距离/前车速度信号，符合原厂"基础信号持续发送"行为。

### 4.3 纯OP 状态机新增测试（opendbc test_macan_mlb.py）
新增 `TestMacanPureOPLongStateMachine`（9 用例），逐条对齐用户 0915 规范：
- LS_Hauptschalter=0 → acc_control=0（关闭）
- LS_Hauptschalter=1 未激活 → 2（待命，踩油门仍 2）
- 激活（TSK_Status 1/2 确认）→ 3
- 激活中踩油门 → 4（超驰）
- 故障 → 6
- stock_st 在纯OP 恒 None（不镜像原厂）
- ACC_02 HUD：激活→Status=3/Prim=1；待命→Status=2/Prim=0

### 4.4 测试结果
- `opendbc/car/volkswagen/tests/test_macan_mlb.py`：**33 passed**（含新增 9 用例）
- `opendbc/car/volkswagen/tests/` 全量：**37 passed, 96 subtests**
- 主仓 `openpilot/selfdrive/car/tests/test_car_interfaces.py -k volkswagen`：**19 passed**

### 4.5 依赖
- 纯OP 中 `long_active = CC.longActive`（OP 自定，非原厂 TSK）→ 纯OP 激活由 OP 自身 long 状态门控，
  不依赖已停用雷达的 TSK 激活。TSK_Status 仅用于 `cruiseState.enabled`/accFaulted 诊断回读。
- 待路试验证：纯OP 下 TSK_Status_GRA_ACC_02 是否如实反映 1/2（engaged/超驰）。
