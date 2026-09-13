# Macan 融合控制模式 + OP巡航速度直接读原厂 (0914)

> 分支：`macan-long-0914` ｜ 主仓库 HEAD：`06d583462` ｜ 日期：2026-09-14
> 本次改动核心目标：**消除 OP 内部 vCruise 与原厂 ACC 巡航速度分裂**（自定义步进导致的同步丢失/纵向退出）。

## 一、功能背景与路线规划

当前适配采用**融合控制模式**：
- 激活 OP 纵向的同时，激活原厂 ACC 雷达参与发送控制信号；
- OP 与原厂 ACC 相互制约：原厂 ACC **刹车指令无条件遵从**，**加速指令 OP 可拒绝**（防止雷达探测不到静止目标导致碰撞）。

长期路线：
1. 先将"融合控制"这条路走完整（本次 0914）；
2. 再开发**纯 OP 纵向控制**，将 OP 从融合方式中剥离。

---

## 二、本次改动点（0914）

### 1. 新参数：`MacanFusionMode`（融合控制模式）
- 位置：`openpilot/common/params_keys.h`
- 类型：`PERSISTENT | BACKUP, BOOL`
- 默认值：`1`（开 = 融合控制，当前恒开）
- 语义：
  - `1` = 原厂 ACC 与 OP 纵向融合控制（**当前模式，恒定为开**）
  - `0` = 纯 OP 纵向控制（**后续开发，暂不可设**，UI 锁定禁止切换）

### 2. OP 巡航速度直接读原厂（cruise.py）
- 文件：`openpilot/selfdrive/car/cruise.py`
- `VCruiseHelper.__init__`：新增 `self.macan_fusion`，判定条件：
  ```python
  self.macan_fusion = (self.CP.carFingerprint == "PORSCHE_MACAN_MK1" and
                       self.params.get_bool("MacanFusionMode"))
  ```
- `update_v_cruise` 中，`macan_fusion` 为真时**强制走"跟随原厂"路径**：
  ```python
  self.v_cruise_kph = CS.cruiseState.speed * CV.MS_TO_KPH
  self.v_cruise_cluster_kph = CS.cruiseState.speedCluster * CV.MS_TO_KPH
  if CS.cruiseState.speed == 0:
      # V_CRUISE_UNSET
  elif CS.cruiseState.speed == -1:
      self.v_cruise_kph = -1
  ```
- **闭环同步机制**：OP 按键只影响原厂（经 OP 转发到 bus2），原厂重新算出 Wunschgeschw 再回灌给 OP —— 保证 OP 与原厂 ACC 巡航速度恒定一致，消除"OP 内部 vCruise 与原厂分裂"（如长按 +5 vs 原厂 +10）。

### 3. UI：融合控制模式开关（sunnypilot 原生）
- 文件：`openpilot/selfdrive/ui/sunnypilot/layouts/settings/vehicle/brands/volkswagen.py`
- 新增 `fusion_mode` toggle：标题 `Fusion Control Mode (Macan)`
- **可见条件**：仅 Macan 且 OP 纵向控制开启（`ui_state.has_longitudinal_control`）
- **锁定为开**：`set_enabled(False)` + `set_state(True)`，只能看不能设（纯 OP 未开发，防误关）
- `_on_enable_fusion_mode` 回调强制写回 `True`，双保险。

### 4. UI：自定义 ACC 增量自动灰（仅 Macan 融合模式开时）
- 文件：`openpilot/selfdrive/ui/sunnypilot/layouts/settings/cruise.py`
- 当 `macan_fusion_on` 为真（Macan + MacanFusionMode=开）时：
  - `custom_acc_toggle` 自动 `set_state(False)` + `set_enabled(False)`（灰色关闭）
  - 短按/长按增量控件随之隐藏
- 其他车型不受影响。

### 5. UI：mici UI 两套
- 文件：`openpilot/selfdrive/ui/mici/layouts/settings/toggles.py`
- 新增 `macan_fusion_mode` 大参数控件，绑定 `MacanFusionMode`
- 同样：仅 Macan + OP 纵向开启可见，`set_enabled(False)` 锁定。

### 6. i18n 翻译（英文原文 + 中文汉化）
- `app_en.po`：英文原文（UI 真实字符串用英文）
- `app_zh-CHS.po` / `app_zh-CHT.po`：中文翻译
  - `Fusion Control Mode (Macan)` → `融合控制模式 (Macan)` / `融合控制模式（Macan）`
  - 长描述 ON/OFF 说明已做中英对照。

### 7. opendbc 子模块：Wunschgeschw 仪表显示源
- opendbc → `2d888f442`（macan-long-0914）
- 仪表盘显示源可选：VcruiseSync 开时透传原厂巡航速度，便于路试验证同步。

---

## 三、需求约束核对（用户原话要点）

1. **仅 MLB 车型 macan 适用**，其他车型不受影响 → 所有改动均以 `carFingerprint == "PORSCHE_MACAN_MK1"` 门控 ✓
2. **UI 开关仅 Macan 且 OP 纵向开启可见** → `fusion_visible = is_macan and op_long_on` ✓
3. **Macan + 融合模式开时，自定义 ACC 增量自动灰色关闭**，其他车型不受影响 ✓
4. **UI 做两套**：tizi/tizi（sunnypilot 原生）+ mici；按键/说明原始英文，中文 .po 增加翻译实现汉化统一 ✓

---

## 四、已知要点 / 坑

- 原厂 `Wunschgeschw` **无效值 = 327.04**（raw 1022 "keine Anzeige"，非 MQB/MEB 的 327.36=raw 1023；差 0.32 一度被误认为信号衰减）。
- ✅ **已对齐（0914 追加）**：`mlbcan.create_acc_hud_control` 写回的无显示哨兵封装为 `_WUNSCH_NO_DISPLAY = 327.04`，opendbc `73f15ddc`，主仓 `efb04fc`，均已推送 `macan-long-0914`。
- `carstate 归零`限制：**>90（m/s）巡航速度无法置入**，为防路试出问题所加的限制。
- OP 纵向控制开关 = **选项→开发者→「sunnypilot 纵向控制（Alpha）」**。

---

## 五、推送与验证记录

- 主仓库 `macan-long-0914`：HEAD=`06d583462`，已 push 至 `origin/macan-long-0914`（同步 0/0）
- `opendbc_repo`：`macan-long-0914` 分支已 push，指向 `2d888f442`（与主仓库引用一致）
- `ai` 子模块：`macan-long-0914` 分支已 push，指向 `36cdacdfe`（0912 CustomAcc step 改动，主仓库 0914 沿用该指针；因远程原不可达，本次补建同名分支推送）
- webui：指针未变（沿用 `1a963cf7e`），不属本仓库维护。

---

## 六、后续路线（下一步）

1. **纯 OP 纵向控制**（融合模式关）：
   - 激活 OP 纵向时**不激活原厂 ACC 雷达**，雷达不再发送控制信号给 OP 提供制约参考赋值；
   - `ACC02 / ACC04 / ACC05` 需 OP 自己生成发送；
   - 当前 `MacanFusionMode` 开关锁死为开，待纯 OP 纵向开发完成后放开。
2. 若走自研按键逻辑，可考虑放弃自定义 ACC 巡航速度（用途不大、实现麻烦），完全匹配原厂按键逻辑。
