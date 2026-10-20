# 上游未移植清单第二轮（进行中，2026-10-20 深夜）

协议同 `upstream_pending_port_20261020.md` §5：**一次只搬一个 group，搬完让探针翻 `DRIFT`，
再改表**。本轮从清单里挑独立、不依赖同批其它条目的条目逐条走。

坐标：我们 `0a52d4c701`（本条之前是 `c5a95ab4eb`），上游 `upstream/test` = `817f4a78c2`
（fetch 后核实未变；`remote.upstream.fetch` 已是通配，phase 0 OK）。

| group | 上游 commit | 我们的提交 | 结果 |
|---|---|---|---|
| carrot/gps | `6ad1f5b099` 导航 GPS 来源收口到 `gps_sources.py` | `0a52d4c701` | 搬完 |

清单 31 条 → **30 条**（`upstream_pending_port.items`），`ported` 段 5 → 6 条。

## 1. `6ad1f5b099` carrot/gps —— 一个来源判据，两处作答

上游原来的毛病是「同一件事答两遍、判据不一样」：

| 位置 | 判据 | 后果 |
|---|---|---|
| 数据层 `_phone_gps_is_usable()` | 导航块过期 + phone 新鲜 + **accuracy < 15 m** + 坐标合法非零 | 30 m 的 phone fix 被**拒绝** |
| UI `gps_source` 属性 | 只有新鲜度 + 非零坐标 | 同一个 30 m fix 被报成 **phone** |

也就是说 UI 能宣称一个数据层根本没用的源。收口后两边都调 `gps_sources.select()`。

### 搬了什么

- 新增 `openpilot/sunnypilot/carrot/gps_sources.py`（84 行，纯函数、无 Params/无时钟）：
  - `Fix`（lat/lon/heading/speed/accuracy/stamp；`heading=None` 表示沿用上一帧朝向）
  - `plausible()`：越界坐标、零岛 `(0,0)`、`> 90 m/s` 瞬移一律拒
  - `fresh()`：**每个源各自的 3.0 s 窗口**（不再是「导航过期」这种跨源判据）
  - `usable()`：新鲜 + 可信 + 源级质量门（只有 `phone` 额外要 accuracy < `PHONE_MAX_ACCURACY_M`）
  - `select()`：固定优先级 `external_navi > phone > device`，返回 `('navi'|'phone'|'device'|'none', fix)`
- `carrot_serv.py`：
  - `_gps_fixes()` 组装三源快照；`update_raw` 的回退分支改成 `select()` 的产物
    （`fix.heading is None` 时不写 `nPosAngle`，即「不发明朝向」）
  - 新增 `update_device_gps(sm)`：device 自车融合位置作为**兜底**，门控与 mapd 一致
    （`llk.status == valid` 且 `positionGeodetic.valid` 且 `gpsOK`），只在外部源全过期时
    避免路线曲率链挂在 `(0,0)` 上；不声明精度、不编朝向；缺服务/空值静默忽略
  - `gps_source` 属性 = `select(...)[0]`，与数据层同源
  - `derive()` 里先 `update_device_gps(sm)` 再 `update_navigation_source()`
- `carrot_man.py`：订阅里加 `liveLocationKalman`（见下「冲突」）
- 新增 `docs/gps_source_priority_20261020.md`（上游原文）、`tests/test_gps_sources.py`（21 例）

### 冲突与本地适配

- `carrot_man.py` 冲突：上游把服务列表写死在 `messaging.SubMaster([...])` 字面量里，
  本树早就抽成 `CARROT_SERVICES` 常量（10 Hz tick 与广播线程各自的 SubMaster 共用同一列表，
  见 2026-10-18 msgq 跨线程崩溃的注释）。按本树写法解 —— 只把 `'liveLocationKalman'`
  加进常量，不恢复字面量。副作用：广播线程的私有 SubMaster 也一并订阅它（上游文档里已
  确认 `carrot_man` 全程用逐服务 `sm.valid/sm.alive`、没有无参 `all_checks()`，
  多一个订阅不改变任何既有可用性门控）。
- `openpilot.cereal.log` 用 `try/except ImportError` 软导入，主机 checkout 没有 opendbc 时
  模块仍可 import、单测可跑（`log is None` → `update_device_gps` 直接返回）。
- `carrot_serv.py` 其余 5 条 ruff 告警（3× `TID251 time.time`、`B007 _pcnf`、`F841 atc_speed_org`）
  是档案前就有的，与本条无关；新增两个文件 ruff 零告警。

### 验证

| 项 | 结果 |
|---|---|
| `tests/test_gps_sources.py` | **21 passed**（上游本机 15 跑 + 6 skip，我们这边 21 全跑） |
| `tests/test_carrot_man.py` | **150 passed**（含既有 `gps_source` 两例） |
| `openpilot/sunnypilot/carrot/tests` 全套 | **684 passed / 6 skipped / 0 errors** |
| `ruff check` 新增两文件 | 干净 |

上游未做、我们也没做：隧道实测、与 llk 精度对比、路线曲率链的实车回归。`device` 兜底只在
外部源全过期时生效，日常（手机连着、导航块在跑）走的仍是 `navi`/`phone`，本条不改变现有体感；
**上车值得看一眼**的是 `carrotManSP.gpsSource` 在手机断开后是否从 `phone` 变成 `device`
而不是掉到 `none`。

## 2. 顺手修掉一处「假 DRIFT」判据

搬完本条，检查器翻了两条 `DRIFT`：

```
DRIFT   6ad1f5b099  path now exists: openpilot/sunnypilot/carrot/gps_sources.py   ← 本条（预期）
DRIFT   f29fd60fbc  path now exists: docs/gps_source_priority_20261020.md        ← 假警报
```

`f29fd60fbc`（三条改动的车机实测记录）当初用 `path_absent docs/gps_source_priority_20261020.md`
当判据，可那个文件是 `6ad1f5b099` 建的 —— 搬完 GPS 那条它必然存在，判据本身是错的。
已把该条换成 `symbol_absent docs/gps_source_priority_20261020.md:"c2df04b19"`
（只有它追加的「车机实测」段落才有的串），并在条目里留了 `probes_note` 说明换判据的原因。

教训：**`docs` 类条目的探针不要指向同批代码条目新建的文件**，要指向本条目自己写进去的那句话。

## 3. 下一条

按清单顺序，仍然独立可搬的 `todo`：`9d722b3acc`（tools 内存历史采样）、
`2ffd3d1758`（radard 为无雷达车保留刚丢的视觉前车）、`bde651b930`（ModelDataV2.meta 车道宽度）、
`830c2e7a79`（carrot 测试 runner 拒绝静默 skip）、`34f7b78b14`（UI 开关）。
