# 模型选项"只看得到小模型" 收尾（第 2 问）2026-10-17 19:56 +08

分支：openpilot `sp-macantest-1017` / ai `sp-macanlong-test`。设备本地时区 +0800。
本轮只做「2) 模型列表只有小模型」，未重启 UI/comma/aid。

## 结论：不是 LFS、不是 catalog、不是 panda，是我们这棵树 merge 后把上游的模型页弄丢了两个块

数据面先排除（实测，用设备真实 params）：
- `get_cached_bundles(qcom)` = **77** 个；`get_cached_bundles(chestnut)` = **17** 个（Deep RL 11 / Master 5 / Preview 1）。
- 缓存键都在：`ModelManager_ModelsCache`(90 KB) / `_Chestnut`(79 KB)，`LastSyncTime*` 19:39 刚刷新过。
- 结论：大模型 catalog **一直在**，问题在 UI 代码。

## 根因 A（主因，真崩）：mici 模型页丢了 `link_toggle` / `refresh_btn`

`openpilot/selfdrive/ui/sunnypilot/mici/layouts/models.py` 与 `upstream/test` 相差 **-78 / +31**：
本树版本 `__init__` 只有 `current_model_info / select_model_btn / cancel_download_btn`，
但 `_update_state()` 里仍每 0.5 s 调 `self.link_toggle.refresh()` / `set_visible(...)` →
**`AttributeError: 'ModelsLayoutMici' object has no attribute 'link_toggle'`**，面板每帧更新链在
任何列表逻辑之前就断了。上游该文件还有：jetlink 模式 `BigMultiParamToggleSP` 开关、
`refresh_btn` + `_refresh_models()`、`_confirm_clear_cache()`、`_model_info()` 驱动的状态行。

处置：整文件回到 `upstream/test` 版本（它本来就有 small/big 双槽位 `_show_folders` +
`_select_hardware`，正是我们要的"跟齐上游"），不再保留本地手改版。本地唯一需要保留的差异是
`cancel download` 的描述文案，上游已有等价 `description=`，不另加。

## 根因 B：活动槽位只读 live `availableBundles`，首 tick 为空 → "No models available"

`model_info.bundles_for_source(source)`：`source == active_source()` 时直接返回
`ui_state.sm["modelManagerSP"].availableBundles`。该消息要 manager 发布一帧后才有（开机、
刷新、manager 重启的头几帧都是空，历史记录里也见过首帧 0）。空列表走到
`_select_hardware` 就弹 `No models available for this hardware yet...`，
用户观感正是"我这台只有小模型"。

处置：live 列表为空时回落磁盘缓存目录（`get_cached_bundles`），只有缓存也空才认"没有模型"。
新增回归测试 3 条 `TestBundlesForSourceFallback`（空 live → 读缓存 / live 优先 / 非活动槽位读缓存）。

## 根因 C：`BigButtonSP.badge_area` 调的两个宽度方法，基类根本没有

`sunnypilot/mici/widgets/button.py:87` 调 `button._title_width_hint()` 与 `_subtitle_width_hint()`，
而 `openpilot/selfdrive/ui/mici/widgets/button.py` 这棵树只有 `_width_hint()`（上游已拆成
title/subtitle 两个）→ cruise / steering 面板、badges 批量渲染 AttributeError。
处置：基类补齐 `_title_width_hint()`（原 `_width_hint` 逻辑）+ `_subtitle_width_hint()`
（底对齐，不扣图标宽），`_width_hint()` 转调 title 版，老调用点不动。

## 根因 D：tici 面板 refresh 按钮缺 `_refreshing` 门控

本树 `refresh_item` 是静态 `REFRESH` + 一次 `LastSyncTime=0` + 弹窗；上游是动态
`FETCHING... / REFRESH` + `_refresh_models()` + `refresh_in_progress(self._refresh_start)` 门控
（offroad 且未在下载且不在刷新才可点）。按用户"两者融合、贴我们实际"的原则：**采用上游实现**，
保留本树"不引入上游 download_item"的决定与 items 顺序不变。

## 验证

- `pytest selfdrive/ui/sunnypilot/tests selfdrive/ui/mici sunnypilot/models/tests -q`
  → **203 passed, 3 skipped, 7 subtests**（修复前同集合 18 failed）。
- 真实 params 下打印选择器（无渲染）：槽位 `小模型 = cd210 (default) (活动中)` /
  `大模型 = cinque terre model v2 (default)`；qcom 10 个文件夹、chestnut 4 个（含 `2026 deep rl models` 11 个模型）。
- 面板对象 `hasattr(layout, 'link_toggle') == True`、`refresh_btn == True`。

## 踩坑记录：设备语言 zh-CHS 会让断言英文文案的测试整片失败

`multilang` 在 import 期读 `LanguageSetting`（本机 = `zh-CHS`）→ `tr()` 直接出中文，
`test_accelerator_ui.py` 断言 `"Nothing on the USB port."` 之类就失败（曾误判为代码回归）。
跑这批测试的正确姿势：临时 `printf 'en-US' > /data/params/d/LanguageSetting` → 跑 → 立刻写回
（本轮已备份/恢复，`cat` 复核 = `zh-CHS`）。**不要**为此改产品代码或断言。

## 未完成 / 下一步

1. 上车的 UI 进程（PID 111920，19:39 启动）跑的还是旧 `models.py` → 面板仍会 AttributeError。
   需要重启 UI 才生效（`sudo systemctl restart comma` 有 19:37 那次 tap-reset 陷阱，
   优先只让 UI 进程被 manager 重新拉起，或先确认 `comma.service` drop-in 防呆在位）。
2. chestnut 槽位在无 chestnut 硬件时由 jetlink 跑，实机选择大模型后仍需点火验证一次。
