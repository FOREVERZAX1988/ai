# 上游 test 第 10 轮 — 进程看门狗 + 可信的 CarParams 快照（2026-10-21）

范围：`7fd88d270b` 与它的修丁 `aab6ed90f8`（同一条必须一起落）。来源是 StarPilot 对比出来的两个缺口。

## 一、活着但卡死的进程

manager 原来只能发现**退出**的进程。一个活着但停止推进的进程从外面看完全正常：占着资源、不报错、
车一直在等一条永远不会来的消息 —— 上次「camerad 重启、modeld 卡死」就是这个形状。

现在被监听的进程每完成一次工作就往 `/dev/shm/wd_<pid>` 写一次心跳，manager 心跳过期就重启它。
只监听 `ui` 与 `camerad`；**控制链（control / selfdrive / planner 三个守护进程）故意不监听** ——
重启它们会在控制输出上留一个缺口，比卡死更糟。

两边时钟必须一致：C++ 侧写 `nanos_since_boot()`（CLOCK_BOOTTIME），Python 侧若用 `time.monotonic()`
（CLOCK_MONOTONIC）就会差出设备的挂起时长，所以 Python 侧也读 CLOCK_BOOTTIME。

**本机的落地程度不一样，这点必须记住：**

| 进程 | 心跳来源 | 现状 |
|---|---|---|
| `ui` | Python | 立刻生效（manager 重启后） |
| `camerad` | C++ `watchdog.kick` | **要重建 camerad 二进制才有心跳** |

而在没有心跳文件时，`watchdog_timed_out()` 返回 `None`、manager 走「从没上报过」的宽限分支 ——
**不重启、不改变任何行为**。所以现在把 camerad 挂上监听是安全的空操作，等哪天重建了二进制它才真的生效。

## 二、不该被信任的 CarParams

设置页原来直接读 `CarParamsPersistent`。车进程刚启动时那个快照可能是 **MOCK**，
于是「没接车的车型」的设置项也会出现。新模块 `sunnypilot/common/car_capability.py` 规定：

- MOCK 指纹永不可用；
- 在线优先用 `CarParams`，离线用 `CarParamsPersistent`；
- 用户强制过指纹时，只接受**那一个**精确车型；
- 上一条 route 的快照只有在匹配强制车型时，才用于决定「设置项能不能显示」，绝不用于启用控制路径。

本树没有 `ForceFingerprint` / `CarModel` 两个键（上游/StarPilot 的强制指纹功能我们没有注册），
所以 forced 分支在这台车上是死代码 —— 调用方全部 try/except，读不存在的键不会炸。

## 验证

- `test_watchdog.py` + `test_car_capability.py`：**30 passed**
- `openpilot/system/manager`：34 passed / 1 failed；唯一的失败是
  `test_restarting_process` 里对 `AudioProcess` 的 isinstance 断言 —— `process_config.py` 自己定义了这个子类，
  `HEAD` 上同样失败，与本轮无关
- `openpilot/sunnypilot/carrot/tests`（含 settings 服务）：**711 passed / 6 skipped**
- 真机手工验证（真 Params + 真 /dev/shm）：心跳写到 `/dev/shm/wd_<pid>`；把时间戳改成 30 s 前，
  5 s 阈值下 `watchdog_timed_out` 返回 `30.00`；`clear` 之后返回 `None`；文件不存在时永不超时
- `scons -j1 openpilot/common/libparams_c.so` 通过：`watchdog.o` 已编入 `libcommon.a`，未触发 lowmemorykiller
- `ruff`：改动的 8 个 py 文件全绿
- `upstream_divergence_check.py --side worktree --pending-only`：phase 2 **4/4**、phase 3 **4/4**

## 下一步（items 剩 4 条）

- `dbe9c7c52c`：SLC 限速突降的舒适松弛 + safe-mode stock 语义（第 6 轮之后才有 stock 语义可用）
- `eval` 三条：`d81eec5899`（视觉限速，2883 行 + 22MB）、`63a6f3211b`（NNFF，127 文件）、
  `d4136d1df0`（依赖 `d81eec5899`）
