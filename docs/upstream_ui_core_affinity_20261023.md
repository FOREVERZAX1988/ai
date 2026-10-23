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
grep Cpus_allowed_list /proc/$p/status    # 期望：大核在线时为大核号，而不是 0
chrt -p $p                                # 期望：与改动前一致（本轮未动调度策略）
grep 'FPS dropped' /data/log/swaglog.*    # 期望：仅有开机首分钟的少量告警
```

## 7. 未决项（需驾驶者拍板，本轮刻意不动）

1. **`UI_CORES=(5,4)` 与控制链撞核**：core5 上是 `card`(CTRL_HIGH 53) +
   `plannerd`/`radard`(CTRL_LOW 51)，而 UI 也是 53。改优先序 `(4,5)`（core4 只有
   `radarcan` 51）在争用上更安全，但这是**控制路径相关的核位决策**，按本仓纪律
   要驾驶者拍板 + 上车验证，不顺手改。
2. **`selfdrive/ui/carrot_ui_sched.ensure_ui_sched_other()` 已移植但无人调用**（死代码）：
   它的契约是把 UI 主线程从 RT 降为 `SCHED_OTHER`，防止 UI 抢占 locationd/sensord。
   本轮查过日志**没有** locationd/paramsd 被饿死的证据（无 loop-time/lagging 告警），
   因此不在路试前盲改调度策略；若后续出现 locationd 抖动，优先接线这个函数。
3. `set_core_affinity()` 与 `get_available_cores()` 的语义混淆只修了调用点与过滤点，
   没有改 `get_available_cores()` 本身（它按 docstring 就该报告本进程掩码），
   以免牵动 modeld 等既有 `config_realtime_process()` 调用点。
