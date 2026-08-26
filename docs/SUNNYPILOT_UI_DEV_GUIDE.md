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

## 新增开关完整检查清单（2026-08-26 确立，po 翻译必做）
> 新增任何 Macan UI 开关/选项时逐项核对，防止漏 po/漏编译/漏联动。
1. params_keys.h 注册参数（BOOL 默认 "0" / FLOAT 默认 "0"）→ 必须重编译 scons -j1 openpilot/common/libparams_c.so（未注册 key 的 Params.get/put 抛 UnknownKeyName 崩 UI）
2. tizi 布局 sunnypilot/layouts/settings/vehicle/brands/volkswagen.py：toggle_item_sp/option_item_sp + DESCRIPTIONS 英文 + 回调 + items 列表 + 子项 set_visible 联动
3. mici 布局 mici/layouts/settings/toggles.py：控件类/实例化 + add_widgets + self._xxx + _refresh_toggles + set_visible 联动（Macan 分支与 else 分支都要加）
4. **po 翻译（老传统，最容易漏）：CHS + CHT 各加 2 条 msgid（开关显示文本 + 描述文本），共 4 条**——漏掉 = 中文 UI 显示英文。英文硬编码（tr/tr_noop），中文全走 po；只做 CHS/CHT，其他语言无 Macan 条目。**坑（2026-08-26 实锤）：po 的 msgid 必须与代码文本逐字符一致——tr_noop 不做 % 格式化，代码里写 81% 就是 81%（写 81%% 会显示成 81%% 且翻译匹配失败）**
5. 控制逻辑读参数：BOOL 用 get_bool、FLOAT 用 get(float) 或 get(return_default=True)（未写入时取默认）+ 1 秒缓存；FLOAT put 必须传 float（str 崩 UI）
6. py_compile 全部改动文件；UI 重启生效；params 新 .so 需重启进程加载
7. 提交推送：主仓 + ai 子模块 macan-long-XXXX 同名分支，push 一律 --no-verify，完事 ls-remote 核实
