# 8088 面板漏看 144 个开关：扫描器只认双引号（2026-10-21）

## 怎么发现的

做第 16 条（把 `VisionSpeedLimitLowLimitThreshold` 上屏）时想顺手确认「屏幕上多了一行，
面板上也该多一行」，于是拿 `carrot/web_settings.py` 的扫描器数了一遍：车机设置树里
**294** 个已声明键，扫描器只认出 **150** 个。差的 144 个全部来自同一个文件——
`openpilot/selfdrive/ui/sunnypilot/layouts/settings/carrot_tuning_items.py`：

```
$ python3 -c "import re;t=open('.../carrot_tuning_items.py').read();print(len(set(re.findall(r\"'([A-Za-z0-9_]+)'\",t))))"
144
```

因为那个文件里每个键都写成 `param='CarrotLeadPreviewEnabled'`（单引号），
而扫描器是：

```python
_KEYWORD_ARG_RE = re.compile(r'"([A-Za-z0-9_]+)"')   # 只认 "
```

同文件里还有三行更专用的正则（`_PARAM_KW_RE` / `_PARAM_KW2_RE` / `_PARAM_POS_RE`），
同样是写死 `"`，但它们只被 `_KEYWORD_ARG_RE` 取代使用，实际生效的只有这一条。

## 影响面（不是「面板少几个控件」这么轻）

| 读点 | 后果 |
|---|---|
| `web_interface.py:428 render_settings_page` | Carrot Tuning 页在浏览器里只剩 1 个 `CarrotWebEnabled`（+ 两个 UI 字符串 `Back`/`OPEN` 和一个 `hyundai`），整页的 Carrot/Developer 调参控件全部不存在 |
| `web_interface.py:439 apply_settings_form` | 那些键不在这页的 `kinds` 里，端口 8088 的前提下**根本提交不上**，不是「显示了但保存失败」 |
| `build_settings_catalog.py:150 ui_page_params()` | 车机自带页那 144 个键进不了 `carrot_settings_sp.json`，于是 7000 的 `/api/settings`（setting profiles、popular-value 上传、intro presets 都读这一份）也一起没有 |

`audit_ui_reach.py` 看不见这个问题：它统计的是「车机设置树里有没有入口」，而入口一直在，
只是 web 面板读不到。这正是它在 `NAME_RE` 注释里已经写过一次的教训
（"Matching only one silently halves the UI surface"），在 web 扫描器这边又犯了一遍。

## 修法

```python
# 两种引号都收，且闭合引号必须与开引号配对（backreference）
_KEYWORD_ARG_RE = re.compile(r'([\'"])([A-Za-z0-9_]+)\1')

def _keys_in(path):
  return [name for _quote, name in _KEYWORD_ARG_RE.findall(text)]
```

`\1` 是必要的：不加它可以匹配 `"X'` 这种跨引号的东西，运行时设置页里 `"` 与 `'`
混用很多，配对约束让误配不可能发生。

修后：车机设置树 294 个已声明键 **294 个全部被认出**（此前 150）。

## 护栏（三条，都做过反证）

`openpilot/sunnypilot/carrot/tests/test_carrot_web_settings.py` 从 7 例变 9 例：

1. `test_a_key_quoted_either_way_is_found` —— 临时目录里写三种行
   （`param='X'` / `param="X"` / 混用），三种都必须被扫出来；
2. `test_no_declared_key_the_pages_name_is_lost` —— 真实设置树扫出的键里，命中
   `params_keys.h` 的数量必须 ≥ 280（不是硬编码 294：加一行不该让测试白过，
   删掉引号处理也过不去），并点名 `VisionSpeedLimitLowLimitThreshold`、
   `CarrotLeadPreviewEnabled` 这两个单引号文件里的键；
3. 原有 7 例不动。

反证（把扫描器换回修复前那版，即旧正则 + 旧 `findall` 返回形式）：

```
FAIL: test_a_key_quoted_either_way_is_found
  AssertionError: 'SingleQuoted' not found in {'DoubleQuoted', 'MixedQuotes', 'B', 'C'}
FAIL: test_no_declared_key_the_pages_name_is_lost
  AssertionError: 150 not greater than or equal to 280 : the page scan lost keys again
Ran 9 tests ... FAILED (failures=2)
```

改回 → 9/9 OK。

## 顺带把目录和面板对齐

- 重新生成 `openpilot/sunnypilot/carrot_settings_sp.json`：380 → **410** 个参数，
  新增 30 个（其中 20 个是 Carrot*/Vision*：`CarrotLeadPreviewEnabled`、
  `CarrotTurnAccelEnabled`、`CarrotBrakingGapEnabled`、`CarrotStoppingLeadEnabled`、
  `VisionSpeedLimitEnabled`、`VisionSpeedLimitLowLimitThreshold` …）。**删除 0 个**。
- 线上确认（车机 offroad，7000 端口按文件 mtime 自动重载，无需重启）：

```
GET http://127.0.0.1:7000/api/settings
VisionSpeedLimitLowLimitThreshold -> True
VisionSpeedLimitLowLimitFilter    -> True
CarrotLeadPreviewEnabled          -> True
items_by_group['carrot_tuning']   : 1  -> 32
```

修复前 `items_by_group['carrot_tuning']` 只有 1 项，是因为它只看到一个 `CarrotWebEnabled`；
现在 32 项。

## 第 16 条收口（阈值上屏）

`carrot_tuning_items.build_dev_items()` 的 Vision Speed Limit 一节新增
`Impossible Limit Threshold`：

- 键是 `FLOAT`（m/s），`use_float_scaling=True` 让控件内部按 ×100 存取，
  屏幕步进 0.50 m/s、范围 0–10.00 m/s；
- `label_callback` 同时显示两种单位：`1.4 m/s (5 km/h)`。**换算只在显示层**：
  存储和 `speed_limit_resolver.py` 读的一直是 m/s，不引入第二套单位，
  也就不存在「两处单位要对齐」的第二条代码路径；
- `enabled=lambda: unified_params.get_bool('VisionSpeedLimitLowLimitFilter')` ——
  上面那个过滤开关关着时这一行灰掉、点不动，因为解析器只在那条路径上读阈值。

护栏 `openpilot/selfdrive/ui/tests/test_vision_limit_threshold_row.py`，6 例，
纯 `ast` + `params_keys.h`（PC 与车机都能跑，UI 包在 PC 上 import 不了）：

| 例 | 钉住什么 |
|---|---|
| `test_the_key_is_float_so_scaling_is_legal` | 键仍是 FLOAT，否则缩放行会写错类型 |
| `test_the_row_asks_the_control_to_scale` | 掉了 `use_float_scaling` 就会把 140 当 1.40 写进去 |
| `test_the_label_shows_km_h_next_to_m_s` | 0 / 140 / 278 / 1000 四个点：`0.0/1.4/2.8/10.0 m/s` 与 `0/5/10/36 km/h` |
| `test_the_km_h_half_uses_the_real_factor` | 因子钉 `0.036`（3.6/100），3.6 与 0.36 肉眼分不出 |
| `test_the_range_covers_a_useful_misread_but_not_a_real_limit` | 上限必须 ≥5 m/s（18 km/h，否则挡不住常见误读）且 ≤20 m/s（72 km/h，否则一开就把真限速也丢掉） |
| `test_the_row_stays_gated_by_the_filter_toggle` | 必须保留 `enabled` 且指向 `VisionSpeedLimitLowLimitFilter` |

## 现在的结果

- `audit_ui_reach.py`：**24 个控制路径开关，24 个有 UI 入口，0 个只能 curl**。
  这是这张表第一次做到 0，并且由新的
  `test_no_control_switch_falls_back_to_curl_only` 直接断言（不再只是「渲染出来的文档这么说」）。
- `docs/carrot_no_ui_switches.md` 随之重生成（23/1 → 24/0）。
- 回归：`test_carrot_ui_reach` 10/10、`test_carrot_web_settings` 9/9、
  `test_vision_limit_threshold_row` 6/6、`test_translations` 48/48、
  `test_float_scaling_contract` + `test_carrot_option_direct_input` 14/14、
  `carrot_tuning_render_smoke` 21/21、`upstream_divergence_check --ref upstream/test` 24/24 + 2/2 + 4/4 无 DRIFT。
- carrot tests 全集 673 例：5 个既有 import 错误（`cv2` 缺失，`test_lead_brake_lights` 等），
  与本次改动无关（stash 前后一致），`test_carrot_server_params` 的 403 相关 1 例在同一进程内
  单独跑是 OK 的（跨用例状态污染，既有问题）。

## 路试待验

- Developer 页 Vision Speed Limit 一节现在多一行阈值：开 `Drop Impossible Vision Limits` 后该行才可点；
  建议先设 1.4 m/s (5 km/h) 左右，确认低值误读被丢、真限速不被丢。
- 8088 面板 Carrot 调参页从 1 个控件变 32 个，手机上看一眼分组是否合理。
