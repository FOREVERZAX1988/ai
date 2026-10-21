# 上游 test 第 8 轮 — 雷达点叠加档位（2026-10-21）

范围：`93b695da88`（`ui: radar point overlay levels - restore carrot ShowRadarInfo scale`）。
**纯显示**，不进控制路径；但这一轮抓到一个「默认就等于关掉整条功能」的参数类型错误。

## 搬了什么

| 上游 | 本仓 | 内容 |
|---|---|---|
| `93b695da88` | 本轮 | `radar_points.py` 的 `radar_info_level()` + 三处按档位剪枝；`visuals.py` 布尔开关换成 4 档 `multiple_button_item_sp`；`ui_state._read_radar_info_level()` 一次性迁移 `CarrotRadarPointsEnabled` |

| 档位 | 画什么 |
|---|---|
| 0 | 不画 |
| 1 | 只画速度框 |
| 2 | + 横向偏移 / 距离 |
| 3 | + 静止目标标记 `*` |

老布尔 `CarrotRadarPointsEnabled` 为真时迁移成 2 档（不叠字的那个视图），然后清掉布尔，
之后 `ShowRadarInfo` 是唯一真源。

## 抓到的真 bug：这个键不能是 BOOL

上游把 `ShowRadarInfo` 声明成 `BOOL`，却当 0..3 档位用。本树实测（隔离 Params 目录、真库）：

```
put_int("ShowRadarInfo", 2) -> TypeError: Type mismatch while writing param
                                b'ShowRadarInfo': proposed_type=int expected_type=ParamKeyType.BOOL
```

两件事同时坏掉：

1. `Params.put_int` 走 `python2cpp((int, BOOL))`，`PYTHON_2_CPP` 里没有这一项 → **写盘前就抛**。
   设置页点一下档位按钮就会炸（`MultipleButtonActionSP._handle_mouse_release` 里那句
   `self.params.put(key, self.selected_button)` 抛到 UI 线程）。
2. `BOOL` 的读取用 `v == b"1"` 归一，**2 和 3 都读回 True/False**，所以就算绕过写入也拉不起来档位。

carrot 自己的 `carrot_settings*.json` 里这个键就是 `"min": 0, "max": 3`，**INT 才是它本来的类型**。
本轮把 `params_keys.h` 的声明改成 `INT` 并重建库。顺带的好处：carrot web 侧 broker 的
snapshot 从 `'True'/'False'` 变成 `'0'..'3'`。

这又是一次「纯逻辑单测全绿、上车才是空按钮」的形状 —— 所以新增 `TestShowRadarInfoKey`：
断言类型是 INT，并逐档 `put_int` → 新句柄 `get_int` 往返一致。谁把声明改回 BOOL，立刻红。

## 测试夹具的两处旧伤（本轮一并修）

`test_moving_point_draws_vector_then_box` 和 `test_slow_point_is_a_star` 在 `HEAD` 上**本来就是红的**，
原因是夹具与实现不同步，而且红得很隐蔽 —— 画不出任何东西，断言从没真正跑过：

1. `_point()` 只有 `vLeadK`/`vLat`，而 `radar_display.select_radar_display_points()` 过滤时读的是
   发布字段名 `vLead`/`yvRel` → 永远是空列表，`render()` 直接 return。
2. 假 `rl.Vector2` 返回 tuple，`_draw_text()` 里 `pos.x` 直接 AttributeError。

修完之后断言也换了口径：比「画出来的字符串列表」（每个标签画两次：shadow + 主体），
而不是上游那种调用计数 —— 计数分不出速度框和偏移标签。

## 库重建

```
scons -j1 openpilot/common/libparams_c.so      # offroad，MemAvailable 1.48 GB，未触发 LMK
lib: /data/.cache/params_lib/libparams_c-1792567160-2908104.so
ShowRadarInfo type = 2 (INT)
put_int/get_int 0/1/2/3 → 全部往返一致
```

`params.cc` 仍由 `common/SConscript` 钉 `-O0`（`26bfd6962e`），所以这条路线照旧安全。

## 验证

- `test_radar_points.py` + `test_radar_display.py`：**40 passed**（HEAD 时是 38 passed / 2 failed）
- `openpilot/selfdrive/ui/tests` 整目录：**141 passed / 1 failed**，唯一的 `test_raylib_ui`
  在整目录顺序下 `HEAD` 同样失败（与本轮无关，单跑通过）
- `ruff`：改动的 5 个 py 文件 **0 新增**（`visuals.py` 的 11 条 ISC002 与 `HEAD` 计数逐条一致）
- `upstream_divergence_check.py --side worktree --pending-only`：phase 2 **7/7**、phase 3 **4/4**

## 待路试

本机 `opendbc/car/volkswagen/radar_interface.py` 有 MLB 雷达接口、且我们已有 Macan 的
Abstandsindex 标定，所以这 4 档不该是空画；路试确认 ①1 档只有速度框 ②2 档多出横向/距离
③3 档静止目标出现 `*`。若 `liveTracks` 在本机根本不出，那按驾驶者的口径应当把这一行直接置灰。

## 下一步（items 剩 7 条）

- `0ba6c81d04`（大 UI 补 Rear Camera 一节 + SLA 去重 + 中文）——参数本机已有，只缺入口
- `7fd88d270b` + `aab6ed90f8`（watchdog，C++ 新目标，两个 commit 一起才成立）
- `dbe9c7c52c`（SLC 限速突降的舒适松弛 + safe-mode stock 语义）
- `eval` 三条：`d81eec5899`（视觉限速）、`63a6f3211b`（NNFF）、`d4136d1df0`（依赖前者）
