# OP 助手（aid）脱离 comma.service cgroup

记录时间：2026-10-17 19:24 +08（19:23:49 切换生效；同刻补 ExecStartPre/LimitNICE 并核实）

## 症状
「答到一半断联」：UI 重启 / `systemctl restart comma` / manager 崩溃时，
`ExecStop=tmux kill-session -t comma` 把 tmux 会话内的 `ai.aid` 一起杀掉。

## 根因
aid 由 `launch_chffrplus.sh` 在 comma.service 的 cgroup（tmux 会话，ppid 为 tmux/manager）里拉起，
生命周期与 comma.service 绑死。

## 修复
1. `/etc/systemd/system/op-aid.service`（独立 unit，User=comma，Restart=always/10s，Nice=-5，
   KillMode=mixed，`StandardOutput=append:/data/ai/logs/aid.log`，StartLimitIntervalSec=0，
   环境变量逐项对齐 launch_chffrplus.sh）。
2. `launch_chffrplus.sh` 改为 `sudo -n systemctl start op-aid`，失败才回退 `keep_alive aid ai/aid.py 5090 &`
   （if/else，不会双开）。**不 enable**：靠脚本触发，避免早于 deps/params 就绪时反复重启刷日志。
3. 三重保险：脚本必成功（comma 有 NOPASSWD:ALL）/ unit 丢失时回退 keep_alive / unit 自带 Restart=always
   → 不会出现「助手起不来得手动启动」。

## 生效验证（2026-10-17 19:24）
- `op-aid.service` active，MainPID=89932，ppid=1，cgroup=`/system.slice/op-aid.service`
- 仅 1 个 aid 实例，监听 0.0.0.0:5090，`curl 127.0.0.1:5090` → 200
- comma.service 仍 active；`systemctl is-enabled op-aid` = disabled（预期，脚本拉起）

## 副作用 / 注意
- `systemctl stop comma` 不再连带停 aid，全停需显式 `systemctl stop op-aid`
- aid 日志改看 `/data/ai/logs/aid.log`（append: 不走 journal），`/tmp/aid.log` 为软链
- 独占 5090：换实例前必须先 kill 旧进程，否则 bind 失败进 Restart 循环
- 回滚：`git checkout launch_chffrplus.sh` + `systemctl stop op-aid`（aid 随下次 launch 回到 tmux 内）
