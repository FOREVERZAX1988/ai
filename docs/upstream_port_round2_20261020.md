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

## 4. 第六条收尾：把「缺 pytest」的 5 条 failures 从允许清单里消掉

`830c2e7a79` 落地时 `scripts/test_carrot_allow.json` 记了 11 条环境缺口：6 条 skip（收集顺序
把 `zstandard` 桩掉）＋ 5 条 `import pytest` 的导入失败。后者是**能靠装依赖解决**的缺口，按
runner 自己的规矩（"能用安装依赖解决的缺口不要往这里塞"）应当清掉。

过程与结论：

| 尝试 | 结果 |
|---|---|
| `pip install pytest` 进 `/usr/local/venv` | **失败**：`OSError: [Errno 30] Read-only file system`（`/dev/sda7` 整根分区 ro） |
| `pip install --no-deps --target /data/.pydeps pytest pluggy iniconfig` | 成功：pytest 9.1.1 / pluggy 1.7.0 / iniconfig 2.3.1（`packaging`、`pygments` 由 venv 满足，不动） |

`/data/.pydeps` 本来就在这台设备的 `PYTHONPATH` 里（`build_carrot_vision.sh` 等脚本同款），
所以 venv 一个字节没改，清掉 pytest 只需删该目录下的三个包：

```
rm -rf /data/.pydeps/{pytest,pluggy,iniconfig} /data/.pydeps/{pytest,pluggy,iniconfig}-*.dist-info
```

装完复跑（`PYTHONPATH` 必须含 `/data/.pydeps`，否则仍是 617 run / 5 failed）：

| 跑法 | 结果 |
|---|---|
| 带 `--allow-from` | **624 run, 0 failed, 6 skipped, rc=0** |
| 不带 `--allow-from` | 624 run, 0 failed, 6 skipped, **rc=1**（6 条 skip 全是 `<-- NOT ALLOWED`，runner 语义正确） |
| 单独 `python3 -m unittest openpilot.sunnypilot.carrot.tests.test_gps_sources` | 21 tests OK —— 反证那 6 条 skip 是收集顺序遮蔽，不是真缺口 |

用例数从 617 涨到 624：那 5 个模块原来整块 `_FailedTest`，现在真的跑起来了，且全过。
`allow.json` 的 `failures` 清空，`_device`/`_run` 两段写明 pytest 装在 `/data/.pydeps` 而不是 venv。


## 5. 第八条 `34f7b78b14` ui/toggle —— 开关从「只能手写 param」抬到 Developer 页

`CarrotLongitudinalSourceEnabled` 早就被 plannerd 每个周期读，我们这棵树的 Params 键
（`params_keys.h:473`）也一直在，但页面上没有入口 —— 只能 adb 进去写 param，效果上
等同于一段死代码。上游这次把它放到 Developer 页 killswitch 邻居旁边，并把「它到底
改了什么」写在描述里（手机端目标速度成为一个规划源；跟车时距、舒适制动、停车点进入 MPC）。

### 搬了什么

| 文件 | 改动 |
|---|---|
| `carrot_tuning_items.py` | `build_dev_items()` 新增 `Longitudinal Control (advanced)` 标题 + `Carrot Longitudinal Source` 开关（位置：`Hardware / Tests` 与 `Navigation Control (advanced)` 之间），新开关描述含「需要手机连接，没有新鲜数据时源自动失效」 |
| `app.pot` / `app_en.po` / `app_zh-CHS.po` / `app_zh-CHT.po` | 三条新 msgid（标题、开关名、长描述），zh-CHS/zh-CHT 用上游原文 |
| `webui` | cherry-pick `d35517c9`（bridge 白名单加该键，两个 UI 对「哪些 param 存在」保持一致）→ 本树落成 `8ae8e69`，父仓指针 `952cd76`→`8ae8e69` |

### 三处本地适配

1. **hunk offset 1 行**：本树 `Traffic Congestion Slowdown` 的描述是 implicit concat（不带
   `+`），上游那行带 `+`，`git apply` 因尾部上下文不符拒收（`patch` 能 fuzz 1 落，但不确定
   落点）。按语义手工插入，新增 13 行与上游逐字一致。
2. **翻译范围比上游宽**：上游只动 pot/en/zh-CHS/zh-CHT 四份；本树每份 `.po` 都带完整
   msgid 清单（de/ja 等也是空 msgstr 的条目，不是缺条目），所以 13 份全部补上、非 en/zh
   留空。先试过跑 `update_translations.py` 自动生成，它把 1.6 万行重排成 2.9 万行噪声
   （顺序与换行全变），已回滚，改手工插入。
3. **webui 是 fork**：`d35517c9` 的分支点是 `75dac813`，我们领先 19 个提交；它只动
   `server/bridge/carrot_tuning_api.py`，该文件自分支点起我们没改过 → cherry-pick 干净。

### 验证

| 项 | 结果 |
|---|---|
| `carrot_tuning_render_smoke.py` | **PASSED 21/21**（DEVELOPER 页真 render：新开关带描述能渲染、9 行导航、字号仍限 40/50/60） |
| `test_translations.py` | **48 passed**（顺带修掉两条档案前就红的：sunnypilot 版 `Excessive %1 actuation…` 的 zh-CHS/zh-CHT msgstr 把 `%1` 吞了 → 单独一条 `e5858f8b77`） |
| `ruff check carrot_tuning_items.py` | 16 条，与 HEAD 完全同数（既有 F401/E501，非本次引入） |
| 探针 | phase 1 **22/22**（新增本条 entry）、phase 2 **23/23** 无 DRIFT |

清单 24 条 → **23 条**，`ported` 13 条。

### 上车才看得到的一点

开关本身默认 OFF，打开后才有「手机目标速度进 plan sources」。真要验，得在 Developer 页
打开它、手机连着导航、看 `carrotManSP`/plannerd 的纵向源是否出现 carrot 那一路；本条
只保证「开关在页面上、写进 param、webui 认得这个键」。

## 6. 下一条

剩余 23 条里，顺序上仍独立的 `todo`：`4d0d11e831`（models：StarPilot 式分块下载 + v25
源映射，体积最大）。其余多为 `eval`（需驾驶者决策）或 `todo-after`（等同批前置）。

## 7. 第九条 `b96f079ca8` latcontrol —— CustomKp 用户级 Kp 缩放（默认 1.0，零影响）

驾驶者的口径：**上游有这个面就要，但要"默认零影响"的形状** —— 默认 1.0，只在非 1.0
时才真的乘进去。本条正是这个形状，所以按原样搬。

### 上游在做什么

`CustomKp` 是 StarPilot 的 Advanced Lateral Tuning "SteerKP" 等价物：一个乘在速度插值
Kp 曲线（`INTERP_SPEEDS` / `KP_INTERP`）上的用户系数，1.0 = stock，夹在 0.5..2.0，
300 帧（≈3s）刷新一次，且**只有值真的变了才重建控制器**（所以积分器不会被每 3 秒
清一次）。上游特意说明：这里已经有 friction/latAccel 覆盖和 auto-tune 开关
（CustomTorqueParams、TorqueParamsOverride*、LiveTorqueParamsToggle、LagdToggle），
只差 Kp 这个面。

### 落地

| 文件 | 改动 |
|---|---|
| `openpilot/common/params_keys.h` | 新增 `{"CustomKp", {PERSISTENT \| BACKUP, FLOAT, "1.0"}}`（1 行） |
| `openpilot/selfdrive/controls/lib/latcontrol_torque.py` | 34 行增量：常量 `CUSTOM_KP_REFRESH_FRAMES=300` / `CUSTOM_KP_SCALE_LIMITS=(0.5, 2.0)`、`_read_custom_kp_scale` / `_apply_custom_kp_scale` / `refresh_custom_kp_scale`，`update()` 开头调用刷新 |
| `openpilot/selfdrive/controls/tests/test_latcontrol_custom_kp.py` | 新增 7 例（上游没有测试） |

`latcontrol_torque.py` 与上游同 commit 版本 `diff` **为空**（34 行增量逐字节相同）。

### 两处刻意的本地偏差

1. **params_keys.h 的落点**：上游把这行插在 `TorqueParamsOverrideLatAccelFactor` 之后、
   Mazda 两条注释块之前；本树没有那个 Mazda 块（`MazdaTorqueDefaultsApplied` 排在 780 行，
   文件整体排法不同）。手工插在 `TorqueParamsOverrideLatAccelFactor` 之后 —— 与上游的
   相对顺序一致，语义相同，只是绝对行号不同。
2. **`_read_custom_kp_scale` 加 try/except 回落 1.0**（这是本轮唯一一处"上游没有"的代码）。
   原因：`params_keys.h` 是编进 `libparams_c.so` 的，本机现在跑的仍是旧库。
   实测（本机、改动前）：
   ```
   Params().get("CustomKp", return_default=True) -> EXC UnknownKeyName b'CustomKp'
   Params().get("BogusKey_xyz_123", ...)         -> EXC UnknownKeyName b'BogusKey_xyz_123'
   ```
   也就是说：只搬上游那 34 行、不兜底，controls 守护进程会在 `__init__` 里直接抛死
   （不是"功能没开"，是**整个横向控制器起不来**）。
   巧的是上游后来自己也被这坑打到 —— `2d9c586376`「fix: survive an unregistered parameter
   key instead of killing the daemon」（**在当前 items 之外的新上游批次里**，尚未移植）就是
   为此新增 `openpilot/sunnypilot/common/param_read.py` 统一兜底。所以这里的就地 try/except
   是**临时形状**：等那批搬进来，改为 `read_float(self.params, "CustomKp", 1.0)`，兜底收归一处。

### 验证

| 项 | 结果 |
|---|---|
| `test_latcontrol_custom_kp.py`（新增） | **7 passed** — 未注册键回落 1.0 / 默认 1.0 不重建控制器 / 1.5 乘曲线 / 5.0→2.0 与 0.1→0.5 夹紧 / NaN 与 inf 回落 1.0 / 值不变保留积分器 / 300 帧节奏（300 帧内只读 1 次） |
| `test_latcontrol_torque_buffer.py` + `test_torqued_lat_accel_offset.py` + `test_latcontrol_torque_ext.py` | **14 passed**（证 `__init__` 里新增 `Params()` 与 PID 重建没碰坏既有行为） |
| `params_keys.h` 语法 | `g++ -std=c++17 -fsyntax-only`（`-Iopenpilot -Iopenpilot/cereal/gen/cpp -I capnp include`）通过；顺带确认 `keys.count("CustomKp") == 1` |
| 探针 | phase 1 **23/23**、phase 2 **7/7** 无 DRIFT（items 8 → 7，ported 29 条） |

### 生效面（为什么叫"零影响"）

- 不设 `CustomKp`，或设为 1.0 → Kp 曲线与改动前逐值相同，`refresh_custom_kp_scale` 也不会
  重建控制器（`abs(scale - self._custom_kp_scale) > 1e-6` 才动）。
- 只有用户主动写一个非 1.0 的值，并且**设备重建过 `libparams_c.so`**（或走能读到该键的
  Params 实现）才会起作用；不重建时走 try/except 回落 1.0，车照开。

### 仍未做的一步

要不要给这个 param 配一个 UI 面（Developer 页滑块 / carrot tuning 项）？上游这条只加了
param 键、没加 UI，上游是靠 webui 的 param 编辑器用的。本树暂按上游口径（无 UI），
若驾驶者要一个手调入口，可另起一条在 `carrot_tuning_items.py` 的 Developer 页加。

## 8. 下一条

剩余 7 条：`51caaa4a3a`（planner: gated non-urgent lead-follow policy，新文件
`lead_follow_policy.py` + 门控挂钩）是最独立的；`077456330f`（注册 FLM / vision
speed-limit 参数键）是 `982fb613f5` 和 `d81eec5899` 的前置；`4b21c8cfdb` + `817f4a78c2`
（stop/depart policy 与它的仿真脚本）成对；`80cd489f0e` 已在登记表里判为"上游 tune 表
无 PORSCHE/MACAN，按没有就不搬"。

另外：上游 test 已经走到 `2d9c586376`（我们登记表 scope 只到 `817f4a78c2`），
`817f4a78c2..2d9c586376` 这 **13 个提交**（StarPilot 整批 port + 那个 unregistered-key
fix）还没进登记表 —— 按驾驶者口径"整批立项单独评估"，应另开一轮做 scope 刷新与逐条裁决，
不要混进本条。

## 9. 2026-10-21 裁决：剩 7 条收成两批，`4b21c8cfdb` 只读评估结论

### 9.1 「接近段」能不能单独摘出来 —— 不能

全部证据来自 `git show 4b21c8cfdb:...` 的只读读取，工作树未动：

1. `get_vision_lead_approach_cap`（policy 480–537 行）不是可独立摘取的 cap：唯一调用点在
   `apply()` 的 per-lead 循环里，它与 `get_close_lead_brake_cap`（radar 近距）、
   `get_vision_slow_stopped_lead_cap`、`get_vision_low_speed_stop_buffer_cap` 共用同一个
   `a_target` 折叠点。摘掉邻居 = 改了顺序语义。
2. 它的输出还被送进 `tracked_vision_lead_approach_needs_immediate_brake`，写
   `self.vision_lead_approach_confirm_t`（确认窗 0.25 s；立即刹车旁路阈值 −1.0 m/s²、
   4.0 m/s 接近速度、0.20 前车刹车、28 m 或 0.85 s·v 距离）。后续 close-stop hold /
   close release / settle / final guard 段读这些 latch。只摘 cap 不摘 latch =
   「接近时压油门」但「停止保持与释放」仍走本机旧形状，是不对称的体感陷阱。
3. 模块顶层硬依赖 `from ...lead_follow_policy import _desired_follow_distance`。
   `lead_follow_policy.py` 来自 `51caaa4a3a`，而那条判的是「需 A/B，暂不搬」。
   ⇒ `4b21c8cfdb` 是 `51caaa4a3a` 的下游：单独搬会 import 失败，把 helper 内联则等于
   偷偷搬了 51caaa4a3a 的一段，登记表就失真了。
4. 结论：**只取 vision approach cap 不成立，只能整块搬**。整块 = 1792 行 policy +
   890 行 tune 面（替换本机 16 行 seed，seed 目前只有 `test_lead_behavior` 一个消费者）+
   27 条纯逻辑单测 + 38 行 planner hook + 1 个默认 0 的 param（`LeadStopDepartPolicyEnabled`）。
   硬前置就是 `51caaa4a3a`。
5. 落地位置已核（真要搬时不用再找）：本机 `longitudinal_planner.py` 在 236–243 行做完
   mpc/e2e/cruise 三路仲裁并 clip `output_a_target`，hook 插在 243 行之后、`apply_signal_prepare`
   之前，即上游同一位置；本机缺的只有把 `effective_t_follow`（carrot t_follow / `mpc.get_t_follow`）
   从 follow-policy 块里 hoist 出来的那一步，`force_decel` 本机已有。

### 9.2 因此 items 收敛为两批，已无可单独搬的条目

| 批 | 条目 | 为什么必须同批 | 本轮裁决 |
|---|---|---|---|
| A latcontrol/FLM | `80cd489f0e`、`982fb613f5`、`d81eec5899`、`077456330f` | 互相 import；`80cd489f0e` 原判据「Macan 0 命中就不搬」失效——它是 import 前置，空命中走回默认 | 暂不搬；只在明确要横向调参手段/FLM 工具/视觉限速时立项，不影响行车 |
| B planner follow/stop-depart | `51caaa4a3a`、`4b21c8cfdb`、`817f4a78c2` | `4b21c8cfdb` 顶层 import `51caaa4a3a` 的 `_desired_follow_distance`；`817f4a78c2` 测的就是 `4b21c8cfdb` | 暂不搬，需上车 A/B（默认 0 的 param + 27 条纯逻辑单测已在位，搬了也不改默认行为，差异只能在路上看） |

登记表本轮只改 `status` / `next` 并新增 `next_batch.batches`，没有改任何代码。

### 9.3 状态

- items 里 0 条可 offroad 单人推进：剩下的都是「整批 + 上车 A/B」或「不影响行车、按需立项」。
- `817f4a78c2` 那条例外：**它是唯一 offroad 就能跑的东西**（纯脚本，不依赖车），但被测对象
  `4b21c8cfdb` 不搬就没有测的东西，所以跟着 B 批。
