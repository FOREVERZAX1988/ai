# 2026-10-17 19:44 +08｜op助手"答到一半断联"现存诱因：会话日志 168MB 巨型 jsonl（已轮转 + 落地自动轮转）

## 1. 证据
- `/data/openpilot/ai_session_logs/s_mtwie4bf_266lhu.jsonl` = **175,494,649 B (168MB) / 148,022 行**，mtime 持续刷新。
- 由 aid（pid 89932, `/usr/local/venv/bin/python3.12 -m ai.aid`）**以 O_APPEND 长期持有**（fd 32，flags `0o2402001`，pos 175491896）。
  多轮压缩上下文后仍按会话 id 追加 → 每轮都要碰这份巨文件，是当前最像"回答到一半掉线"的元凶。
- 本机内存 3607MB / 可用 1801MB；/data 仅剩 4.3G(85%)。

## 2. 处置（不动进程，无需重启 aid）
1. 流式压缩归档：`gzip -1 -c <jsonl> > archive/s_mtwie4bf_266lhu.20261017_194405.jsonl.gz` → **49MB**，`gzip -t` 校验 OK。
2. **copytruncate**：`: > <jsonl>`。因 fd 带 O_APPEND，写指针自动回到新 EOF。
3. 实测验证：`fdinfo/32 pos 175494649 → 2595`，日志立即重新增长，aid pid 89932 不变、`curl :5090=200`、journal 5min 无 error/traceback。
   → 归档在 `ai_session_logs/archive/`，**数据零丢失**。

## 3. 已落地自动轮转（防再发生）
`/etc/logrotate.d/ai-session-logs`（root:root 644，`logrotate -d` 通过）：
```
/data/openpilot/ai_session_logs/*.jsonl {
    su comma comma
    size 50M
    rotate 3
    compress
    copytruncate
    missingok
    notifempty
    dateext
    dateformat -%Y%m%d-%H%M%S
}
```
- 宿主已有 `logrotate-hourly.timer`（每小时）+ `logrotate.timer`（每日），**无需新建 timer**。
- 重装（`/etc` 可能被 AGNOS OTA 换根清掉）：
  `sudo install -m 644 -o root -g root <上面这段配置> /etc/logrotate.d/ai-session-logs && sudo logrotate -d /etc/logrotate.d/ai-session-logs`

## 4. 结论口径
- 断联三条历史根因（libparams_c.so 就地 re-link / cgroup 连坐 / 会话日志膨胀）中，cgroup 已由 op-aid.service 修复并生产验证，本次补上日志膨胀。
- 仍需观察：日志稳定在 50MB 阈值内轮转后，长回答是否还断。若仍断，下一步抓 aid 侧流式写入/上游超时（非日志因素）。

## 5. 当前完整体检（19:43）
comma active NRestarts=0；manager 111645/111823；UI 111920；op-aid active、pid 89932 存活 20min+、HTTP 200；pandad 在跑。
磁盘 /data 4.3G 空闲(85%)；`tool_results/s_mtwie4bf_266lhu` 350MB（本会话外置结果，可后续清理）。

## 6. 未完成
- **LKAS 故障仍欠一次 route 落锤**：`/data/media/0/realdata` routes=0，需上车点火短测（≥15s）。
