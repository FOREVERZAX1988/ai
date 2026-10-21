# 上游 test 第 9 轮 — 屏幕入口补齐 + 中文译文（2026-10-21）

范围：`0ba6c81d04`。这一轮没有新逻辑，全是「东西已经在跑、屏上却没入口」那类缺口。

## 搬了什么

| 位置 | 内容 |
|---|---|
| `cruise.py` | 去掉**重复的 Speed Limit 按钮**：`items` 列表里 `sla_settings_button` 出现两次，巡航面板真的画两个；只被它用到的两行 import 一并删 |
| `steering.py` | 新增 `SteerRatioRate`（30–200%，100 保持原厂）与 `CustomSR`（0.1 单位，>10 才生效，0=原厂） |
| `carrot_tuning_items.py` | 导航页补 **Rear Camera** 一节（`AutoNaviRearCameraHoldDistance`）；速度页补 **Lane Line Curve Speed Gate**（`UseLaneLineCurveSpeed`）；Developer 页补 **ONNX Vision Detection (BSD / Lane)** 五条阈值与间隔 |
| `app_zh-CHS.po` / `app_zh-CHT.po` | 合并上游填好的译文（CHS +110 条、CHT +20 条） |

## 为什么这些旋钮值得上屏

`SteerRatioRate` / `CustomSR` 在 `openpilot/sunnypilot/common/lateral_arbitration_params.py`
和横向解析路径里**早就在读**，主控制进程每帧都在用；在此之前 Macan 车主只能从 web UI 改。
ONNX 五条的取值范围是照 `carrot/xiaoge/v_asm_server.py` 里的 clamp 抄的 —— 超出范围服务器会
静默夹住，所以 UI 干脆不给出会失效的值。

## 译文的并法（与上游不同）

上游这个 commit 是**整段追加 737 行**到 `.po` 末尾。本树的 `.po` 比上游大（自有 fork 字符串
2176 条 vs 上游 1678 条），整段覆盖会跟既有条目撞车，所以改成集合差合并：

1. 只追加本树没有的 msgid 块（CHS 110 / CHT 20）；
2. 本树有该 msgid 但 `msgstr` 还是空的，用上游译文填上（CHT 命中 2 条）；
3. 本树既有译文一条不动。

实测重复 msgid 计数与 `HEAD` 完全一致（CHS 2 / CHT 3，都是既有），`msgfmt` 本机没装，
用正则复核了条目数（CHS 2178→2288、CHT 1910→1930）与空 `msgstr` 计数。

## 验证

- `build_navi_items()` / `build_speed_items()` / `build_dev_items()` 直接构造：**25 / 36 / 32 项**
  （headless 下 `raylib` 字体告警是环境噪声，不是错误）
- 9 个新键在 `params_keys.h` **早已注册** → 本轮不需要重建 `libparams_c.so`
- `ruff`：三个文件与 `HEAD` 逐条一致（`cruise.py` 反而从 3 条降到 1 条，F401 清掉）
- `test_carrot_ui_reach.py` + `test_feature_support.py`：**23 passed**
- `upstream_divergence_check.py --side worktree --pending-only`：phase 2 **6/6**、phase 3 **4/4**

## 下一步（items 剩 6 条）

- `7fd88d270b` + `aab6ed90f8`：process watchdog（C++ 新目标，两条一起才成立）
- `dbe9c7c52c`：SLC 限速突降的舒适松弛 + safe-mode stock 语义
- `eval` 三条：`d81eec5899`（视觉限速，2883 行 + 22MB）、`63a6f3211b`（NNFF，127 文件）、
  `d4136d1df0`（依赖 `d81eec5899`）
