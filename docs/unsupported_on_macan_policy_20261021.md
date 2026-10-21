# 上游功能「已移植但在本车不可用」的处理口径（2026-10-21 驾驶者拍板）

## 口径
上游有的功能**全部拉取、按上游写法原样落地**，不因为 Macan 用不上就删代码或改分支：
删掉的东西下次 pull 都会以冲突形式回来。对本车用不了的功能，处理方式是：

1. UI 上**保留那一行**（看得见 = 知道自己这部分搬过、只是不支持），
2. 渲染成**灰色**、**默认关**、**点不动**（无法开启），
3. 描述里追加一句原因（为什么这台车用不了）。

这样「已支持 / 已移植但不支持 / 还没移植」在屏幕上是可区分的，不用翻文档。

## 落地机制（一个表驱动两半）

新增 `openpilot/sunnypilot/carrot/feature_support.py`：

- `UNSUPPORTED` —— 唯一登记表。每行：`param`（UI 写哪个键）、`cars`（在哪些 fingerprint 上无效）、
  `reason`（屏幕上显示的原因）、`off`（`enforce()` 写回的值）、`on_screen`（是否真有设置页开关）。
- `ui_enabled(param)` → 给 `toggle_item_sp` / `option_item_sp` 当 `enabled=` 用；
  控件自己负责置灰 + 吞掉点击（`system/ui/sunnypilot/widgets/{option_control,toggle}.py`）。
  传的是 callable，每帧重算，所以换车/CP 变化不用重建页面。
- `describe(param, base)` → 不支持时把原因拼进描述。
- `enforce(params)` → carrot_server 启动时跑一次，把表里的键强制写回 off。
  为什么要它：老版本留下的值、或从**别的车**的 Params 备份恢复出来的值，会让一个 UI 上已经灰掉的
  开关在背后照样生效。幂等，只在值不为 off 时写，键不存在（= 走注册默认，本来就是关）时不动。
- `OUR_CARS` —— 只对这台车做判定（`PORSCHE_MACAN_MK1`）。fingerprint 未知（新装/还没跑过 card）时
  一律当作「支持」，宁可让开关活着一小会儿，也不要在拿不到 CP 时把整页灰色化。

## 当前登记的两条（都有代码里的自述证据）
| param | 上游描述里的限制 | Macan 上的事实 |
|---|---|---|
| `AutoGasSyncSpeed` | Tesla / BYD only | 网关没有任何回写 ACC 设定速度的通道 |
| `EnableRadarTracks` | BYD only（角雷达 track 灌进 radar interface） | Macan 的 ACC 模块内部消化目标表，没有可灌的 track |

## 以后新增一条的流程
1. `feature_support.UNSUPPORTED` 加一行（param / cars / reason / off）。
2. 该 param 的设置页条目加 `enabled=feature_support.ui_enabled('<param>')`，
   描述用 `feature_support.describe('<param>', tr('...'))`。
3. 跑 `python3 -m pytest openpilot/sunnypilot/carrot/tests/test_feature_support.py`。

## 防「以后又改名」的显式断言（test_feature_support.py, 16 条）
- 表里每个 `param` 必须在 `common/params_keys.h` 里真实存在 —— 上游改名 → 红，而不是变成死开关。
- 设置页里**任何**带 `param='X'` 关键字的调用，若 X 在表里，就必须带 `enabled=`，且值必须是
  `feature_support.ui_enabled('X')` —— **按 AST 解析、按 `param=` 关键字定位，不依赖工厂函数名**
  （所以重命名 `toggle_item_sp` 之类的 helper 不会把这个检查悄悄失效）。
- `enforce()`：强制关、幂等、别的车不动、键缺失不动、已经是关就不写。
- 未知平台（fingerprint=None）不得把任何东西判成不支持。

## 待路试/上机确认
- 屏幕上看两行：设置 → **Start / Engage** 页的 `Auto Gas Sync Speed`（build_start_items）、
  设置 → **Vehicle** 页的 `Enable Radar Tracks`（build_vehicle_items），
  都应为灰色、默认关、点了不动，描述带原因。
- carrot_server 启动日志若出现 `forced off (not supported on this car): ...` 说明确有脏值被清掉。
