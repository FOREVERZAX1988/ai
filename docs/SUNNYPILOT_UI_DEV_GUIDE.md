# sunnypilot UI 功能设置项开发指南

## comma 设备架构（重要背景，2026-08-21 用户权威解释）
- **sunnypilot** = 这个辅助驾驶 fork 的总称
- **tici** = comma 3（一代）
- **tizi** = comma 3x（二代，**当前 Macan 调机主力设备**）
- **mici** = comma 4（屏幕小 → **UI 独立一套**）
- 两套 UI **按设备型号互斥加载**（同一时刻只有一套在跑）：
  - tici / tizi → **sunnypilot 布局**：`selfdrive/ui/sunnypilot/layouts/`
  - mici → **mici 专用布局**：`selfdrive/ui/mici/layouts/`
- **加功能设置项：两套布局都要加**（用户两台设备都有：tizi + mici）

## 添加步骤（以 MacanJerkLimit 为例，commit 6c5a4884a + 4f76abd77）

### 1. Params 注册（必须，白名单制）
- 文件：`common/params_keys.h`（git 仓库根 /data/openpilot）
- 示例：`{"MacanJerkLimit", {PERSISTENT | BACKUP, FLOAT, "0"}}`
- **不注册 → Params().get/put 可能被拒绝或类型不符**（白名单制）
- FLOAT 参数代码读取：`float(Params().get("MacanJerkLimit") or 0.0)`，建议带 1 秒缓存（time.monotonic）避免高频读

### 2a. sunnypilot 布局（tici/tizi 用）
- 文件：`selfdrive/ui/sunnypilot/layouts/settings/vehicle/brands/volkswagen.py`
- 开关：`toggle_item_sp(tr("..."), "PARAM", initial_state=..., callback=..., enabled=lambda: not ui_state.engaged)`
- 数值步进：`option_item_sp(tr("..."), "PARAM", min_value=0, max_value=300, value_change_step=10, use_float_scaling=True, label_callback=lambda v: "Off" if v == 0 else f"{v/100:.1f} m/s³")`
  - `use_float_scaling=True` → 存的是真实值×100（如 1.8 = 180），label_callback 负责显示
- 可见性：**品牌布局文件本身按车型隔离**（该文件只对 VW/Macan 显示），无需额外判断

### 2b. mici 布局（comma4 用）
- 文件：`selfdrive/ui/mici/layouts/settings/toggles.py`（类 `TogglesLayoutMici`）
- 开关（BOOL）：`BigParamControl(tr("..."), "PARAM")`
- 多选循环：`BigMultiParamToggle(tr("..."), "PARAM", ["a", "b"])` —— **注意它存的是选项索引（0/1/2...）不是选项值**！
- FLOAT 数值：需**自定义控件**（继承 `BigMultiToggle` 覆盖 `_handle_mouse_release` 存选项值本身）——参考本仓库 `MacanJerkControl`（toggles.py:16）
- 可见性：`if ui_state.CP is not None and ui_state.CP.carFingerprint == "PORSCHE_MACAN_MK1":` + `set_visible(True/False)`
- 三处接入：`add_widgets` 列表、`self._xxx = xxx` 存储、`_refresh_toggles`（BOOL 开关才需要）

### 3. po 翻译
- 文件：`selfdrive/ui/translations/app_zh-CHS.po` / `app_zh-CHT.po`
- 加 `msgid "英文原文"` / `msgstr "中文翻译"` 条目
- 两套布局可用不同 msgid（各自翻译），不冲突

## 踩坑记录
1. **BigMultiParamToggle 存索引不存值** → FLOAT 参数必须自定义控件（存选项值本身）
2. **可见性机制不同**：sunnypilot 布局靠品牌文件隔离；mici 布局靠 `ui_state.CP.carFingerprint` 判断 + set_visible
3. **params_keys.h 白名单**：不注册的参数 Params API 可能拒绝
4. **生效方式**：改布局文件 → 重启 UI/设备生效；改代码（longcontrol 等编译模块）→ 重启设备（scons 自动重建）
5. **运行中改参数值**：代码里带 1 秒缓存的话，改 Params 值 1 秒内生效（无需重启）；首次加载新代码才需要重启

## 当前状态（2026-08-21）
- 当前调机设备 = **tizi（comma3x）** → sunnypilot 布局生效（MacanJerkLimit 数值步进项可见）
- 用户另有 **mici（comma4）** → mici 布局生效（循环切换项可见）
- MacanJerkLimit 双布局均已添加并推送（macan-long-0821）
