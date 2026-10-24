# 「卡 UI」根因：UI 永远绑不回大核（上游同源缺陷）

> 结论先行：这不是画面卡在某一帧，也不是 UI 崩溃闪退，而是 **UI 进程的生命周期内
> 无法重新绑定到任何大核**，长期钉在 core0 上渲染 → target 20 fps / 实测 8~17 fps。
> 缺陷在 `upstream/test` 里逐字节存在（blob 相同），**不是本地回归**。

## 1. 现象与判据

| 观测 | 值 |
|---|---|
| UI 进程 | 活着（manager `processes[].running=True`），非崩溃 |
| UI 调度 | `SCHED_FIFO` prio 53 |
| UI 亲和性 | `Cpus_allowed_list: 0`（单核，小核） |
| 日志 | `FPS dropped below 20: 17 / 13 / 8` |
| 内核核集 | `online = 0-3,6-7`，`cpu4/5 = 0`（`possible=present=0-7`） |

## 2. 根因链（两层同一处错误）

`selfdrive/ui/ui.py` 开机 `config_realtime_process(0, Priority.CTRL_HIGH)` 把**自身亲和掩码
收窄成 `{0}`**。之后：

1. `resolve_ui_cores()` 调 `get_available_cores()`，而后者返回的是**本进程掩码**（不是内核
   online 核集）。掩码里永远只有 `{0}` → `UI_CORES=(5,4)` 永不命中 → 恒返回 `[]`。
2. 渲染循环里 `if COMMA_HARDWARE and os.sched_getaffinity(0) != ui_cores:` 因此
   每帧都进分支，但 `set_core_affinity([])` 直接返回空集 = **no-op**。
   "reaffine after power save offlines our core" 这段**在整个进程生命周期内从未生效过**。
3. `set_core_affinity()` 自己又用同一个掩码做 "online" 过滤
   （`usable = [c for c in cores if c in available]`）→ 即使上层算对了目标，也会被滤掉。

所以即使 core_ctl 按负载把 cpu4/5 拉上线，UI 也**永远绑不过去**；UI 不再制造大核负载 →
core_ctl 很快又把 4/5 关掉 → 常驻卡顿。这条因果链解释了「重启后还是卡」。

## 3. 证据（A/B，可复跑）

复现条件：进程自身掩码 `{0}`，内核 online 含 cpu4。

```
模拟 UI 自身掩码 : [0]
kernel online    : [0, 1, 2, 3, 4, 6, 7]
旧逻辑 resolve   : []    <-- 修复前的实际行为
新逻辑 resolve   : [4]   <-- 修复后
```

上游同源判据（补丁前的 HEAD）：

```
openpilot/selfdrive/ui/ui.py         HEAD=e543febf07e9  upstream=e543febf07e9  => 逐字节一致
openpilot/common/realtime.py         HEAD=d0002a1ce790  upstream=d0002a1ce790  => 逐字节一致
```

## 4. 修复（126d466638）

- `common/realtime.py`：新增 `get_online_cores()`（解析 `/sys/devices/system/cpu/online`，
  含 `0-3,6-7` 这类区间语法与回退）；`set_core_affinity()` 的 online 过滤改用它。
- `selfdrive/ui/ui.py`：`resolve_ui_cores()` 改用内核 online 核集；开机
  `config_realtime_process(resolve_ui_cores() or 0, ...)`；循环内的回绑**限频 1 次/秒**，
  避免"待回绑"状态退化成每帧一次 syscall。
- `common/tests/test_realtime.py`：`12 passed`，含回归 pin
  「自身已钉在 core0 的进程仍能拓宽到 online 大核」。

## 5. 生效条件（踩过的坑）

manager 以 fork 拉起子进程，子进程的 `importlib.import_module()` 会命中 manager 启动时
缓存进 `sys.modules` 的**旧模块**。所以改完 `common/*.py` 只重启 UI 进程会得到

```
ImportError: cannot import name 'get_online_cores' from 'openpilot.common.realtime'
→ ui is dead with 1 → 反复重启
```

**结论：改 common/ 下的模块，必须整栈重启（等效重启设备），不能只重启单个进程。**

## 6. 重启后的验收清单

```bash
p=$(pgrep -f 'selfdrive[.]ui[.]ui' | head -1)
grep Cpus_allowed_list /proc/$p/status    # 期望：4（4 离线时为 5；4/5 都离线时落 0-3 属预期，见 §7.3）
chrt -p $p                                # 期望：与改动前一致（本轮未动调度策略）
grep 'FPS dropped' /data/log/swaglog.*    # 期望：仅有开机首分钟的少量告警
```

## 7. 决策记录（2026-10-24 定案）—— 原「未决项」已闭环

### 7.0 实测 RT 核位图

`grep -rn config_realtime_process --include=*.py openpilot/` 量到的当前分配：

| 核 | RT 使用者（FIFO 优先级） |
|---|---|
| 4 | `radarcan` 51 —— 只有它 |
| 5 | `card` 53、`plannerd` 51、`radard` 51、`radard_dpath` 51 |
| 6 | `selfdrived` 53、`controlsd` 53、`dmonitoringmodeld` 5 |
| 7 | `modeld` / `modeld_v2` 54 |
| 0-3 | `locationd`/`paramsd`/`lagd`/`calibrationd`/`torqued`/`dmonitoringd` 全为 5；`sensord` 绑 1 |

`/sys/devices/system/cpu/online` 重启后空闲态实测 = `0-3,6-7`：**core4/5 常态离线**。
core_ctl 只把 6/7 留在大核在线集里（`active_cpus=2` / `max_cpus=4` / `min_cpus=1`）。

> 旧分析里「`card`/`selfdrived`/`controlsd` 全绑 core4」是历史状态，已被上游拆开，
> 不能再拿它当核位决策依据（本条纠正过一次误判）。

### 7.1 `UI_CORES` → `(4,5)`（本轮已改，待上车验证）

- 旧 `(5,4)` 让 UI 优先落 core5，而 core5 上正是 `card`：**同核 + 同 FIFO 53 + 分时轮转**，
  UI 的整屏渲染是唯一能让 `card` 抖一下的邻居。
- core4 的 RT 邻居只有 `radarcan`（51，且是可选角雷达路径），争用代价低一个量级。
- 为了让优先序可测，`common/realtime.py` 新增纯函数
  `pick_online_core(preference, online=None)`，`ui.py` 的 `resolve_ui_cores()` 改为调用它。
  新增 4 条单测（含「4/5 都不在线 → 返回 `[]`，由调用方回退」），
  `common/tests/test_realtime.py` = **16 passed**，ruff 干净。
- 生效条件同 §5：`ui.py` 与 `common/realtime.py` 都会被 manager 缓存，**必须整栈重启**。

### 7.2 `ensure_ui_sched_other()`：定案「保留但不接线」

- 已在文件头加 `NOT WIRED` 注释（含决策日期与本文位置），避免下一轮又被当成
  「忘接线的回归」重开一遍。
- 不接线的理由：把 UI 从 FIFO 53 降到 `SCHED_OTHER`，等于用**已修好的帧率**去换
  一个**没测到的饿死**。日志里没有 locationd/paramsd 的 loop-time 或 `Lagging` 证据，
  本轮不动调度策略。
- 它是第一顺位的备用杠杆：若路试出现 locationd lag，按 §7.3 的判断顺序第一个动它。

### 7.3 仍然开着的唯一一项（留给路试判据，本轮刻意不动）

core4/5 离线（常态）时 UI 落 0-3，与 locationd/paramsd（同核、FIFO 5）共存；UI 是 53，
会抢在它们前面。这条因果只能靠路试判据决定往哪边走：

| 路试观测 | 结论 | 动作 |
|---|---|---|
| 出现 `locationd` loop-time / `Lagging` | UI 抢了定位 | 接线 §7.2，把 UI 降 `SCHED_OTHER` |
| 无此告警、但 UI 帧率仍掉 | 问题是「大核没常在线」 | 改 core_ctl（`active_cpus`/`not_preferred`）让 core4 常在线，单独评估 |
| 两者都没有 | 本议题关闭 | 只保留记录 |

### 7.4 上一轮遗留的一条（不变）

`set_core_affinity()` 与 `get_available_cores()` 的语义混淆只修了调用点与过滤点，
没有改 `get_available_cores()` 本身（它按 docstring 就该报告本进程掩码），
以免牵动 `modeld` 等既有 `config_realtime_process()` 调用点。

## 8. 重启后验收（2026-10-24 13:18，uptime 1:47）

整栈重启后实测（§5 的生效条件已满足，不是单进程重启）：

| 观测 | 期望（§6） | 实测 | 判定 |
|---|---|---|---|
| UI 进程 | 活着 | pid 73596 `openpilot.selfdrive.ui.ui`，SCHED_FIFO 53 | OK（调度策略未动） |
| `Cpus_allowed_list` | 不再是 `0` | **`0-3,5-7`**（改动前恒为 `0`） | 根因已修：掩码不再被收窄成单核 |
| 内核 online | — | `0-3,6-7`（core4 与 core5 均离线） | §7.3 场景 |
| `FPS dropped` | 仅开机首分钟少量 | 当前 swaglog 计数 **0** | 空闲态无掉帧告警 |
| `locationd` loop-time / `Lagging` | 无 | `grep` 为空 | 未见 UI 抢定位 |

回归用例：`openpilot/common/tests/test_realtime.py` **16 passed**；
`realtime.py` / `ui.py` / `carrot_ui_sched.py` ruff clean。

**结论与边界**：§7.1 的 `UI_CORES → (4,5)` 与 `pick_online_core()` 改动**机制层面验收通过**——
进程首次不再被钉死在 core0。但上表是**offroad 空闲态**观测，`FPS` 目标 20 的成立要靠渲染负载，
所以 §7.3 那张判据表的「两者都没有 → 议题关闭」**还不能据此结案**，仍欠一轮实车路试：
路试里若 UI 帧率稳住且无 locationd 告警，才按第一行/第三行判；若 core4/5 长期离线导致掉帧，
走「改 core_ctl 让 core4 常在线」那一行（`ensure_ui_sched_other()` 保持 §7.2 的不接线定案）。
