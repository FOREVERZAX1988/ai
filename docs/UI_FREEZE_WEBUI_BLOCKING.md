# UI「卡住」/ 点不动任何图标：webui 状态轮询阻塞事件循环

> 适用：comma 设备（AGNOS）上 openpilot + 本机 webui。
> 现象：浏览器能打开 webui，但**点任何图标都没反应**，设备同时**发热**。
> 本文是 2026-10-01 实测定位出的真因，不是推测。

## 一句话结论

**不是 ui 进程卡、也不是 msgq**，而是 webui 自己的状态 hub 在**同步**做重活：
`_device_loop()` 每 ~2.5s 调一次**未缓存**的 `verify_agnos_update()` —— 它要对非活动槽的
每个 `full_check` 分区重新做 sha256（每次约 **70MB 块 IO / ~400ms**），
同时 `HARDWARE.booted()` 每秒 spawn ~10 个 `sudo`。
这 400ms **同步阻塞在 HTTP 请求处理里** → 整个 webui 事件循环被堵死 → 图标全部点不动 + 疯狂读盘发热。

## 实测证据（修复前 → 修复后）

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| `/api/opui/agnos`、`/api/opui/home` 单次耗时 | 0.407 / 0.447 / 0.419 / 0.408 / 0.486 / 0.441 s | **0.006 – 0.018 s（约 30×）** |
| `webuid` CPU | 12.6%（稳定） | ~0% |

## 第二个坑（比 bug 本身更容易骗人）：补丁提交了 ≠ 跑起来了

第一次修完用户仍然点不动，原因是：**补丁在 webui 子模块里已经提交（`381be33`），
但正在运行的 `webuid` 是开机时启动的，早于补丁** —— 也就是说设备一直在跑旧代码。

→ 教训：**改完 webui/manager 侧代码，必须让对应进程重启**（`restart_service(name="webuid")`，
或让 `keep_alive` 拉起），否则"我修好了"只是磁盘上的事实，不是运行时的事实。
排查时先对：`ps -eo lstart,pid,args | grep webuid`（启动时间）vs `git -C webui log -1 --format=%cd`（提交时间）。

## 定位手法（可复用）

```sh
# 1) 直接量接口耗时，别猜
for i in 1 2 3; do curl -s -o /dev/null -w '%{time_total}\n' http://127.0.0.1:5080/api/opui/home; done
# 2) 看是谁在吃 CPU
ps -eo pid,pcpu,comm,args --sort=-pcpu | head
# 3) 看阻塞点：在 hub/device loop 里找未缓存的高成本调用
grep -rn "verify_agnos_update\|booted()" webui/server/
```

## 修法

`webui/server/bridge/agnos_api.py`：给 `verify_agnos_update()` 的结论加 TTL 缓存
（`_VERIFY_TTL_SEC = 60` + manifest / job state 文件的 mtime 作为 cache key），
install 进度一变就立刻失效，而不是干等 TTL。提交：webui `381be33`
*perf(state hub): stop the AGNOS and startup gates from hammering the device*。

## 相关

- 别把这条和 **msgq-ipc_pyx** 混淆：`Driving State unavailable: No module named msgq-ipc_pyx`
  是**另一个**历史问题（msgq Python 绑定没编译），它只影响状态显示，**不会**让图标点不动。
  排查时先确认它是否还能复现（`import msgq.ipc_pyx`），别拿旧结论当新证据。
- 设备日志路径与取日志的工具见 `ai/docs/DEVICE_LOG_PATH.md`。
