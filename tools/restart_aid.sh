#!/usr/bin/env bash
# restart_aid.sh — 无人值守重启 ai.aid（op 助手服务）
# 用法: nohup bash restart_aid.sh [DELAY_SEC] >/dev/null 2>&1 &
# 时序: sleep DELAY → 重启 → 验证记录
#
# 2026-10-17 起 aid 跑在独立 unit op-aid.service (/etc/systemd/system/op-aid.service),
# 以便活过 `systemctl restart comma`。必须用 systemd 重启: 若手动 pkill + 重新起,
# 新进程不是该 unit 的 main PID, Restart=always 会再拉一个 → 双开抢 5090。
# 手动方式只保留为 unit 不存在(AGNOS OTA 换根后)的兜底。
set -u
DELAY="${1:-45}"
LOG_DIR=/data/ai/logs
mkdir -p "$LOG_DIR"
echo "[$(date '+%F %T')] restart scheduled (delay ${DELAY}s)" >> "$LOG_DIR/restart.log"
sleep "$DELAY"

if systemctl cat op-aid.service >/dev/null 2>&1; then
  echo "[$(date '+%F %T')] restarting via 'systemctl restart op-aid'" >> "$LOG_DIR/restart.log"
  sudo -n systemctl restart op-aid
else
  echo "[$(date '+%F %T')] op-aid.service missing, legacy pkill + start_aid.sh" >> "$LOG_DIR/restart.log"
  pkill -f "[p]ython.* -m ai\.aid" 2>/dev/null
  sleep 3
  cd /data/openpilot
  nohup bash ai/scripts/start_aid.sh > "$LOG_DIR/aid.log" 2>&1 &
  sleep 4
fi

if pgrep -f "[p]ython.* -m ai\.aid" >/dev/null; then
  PID=$(pgrep -f "[p]ython.* -m ai\.aid" | head -1)
  CG=$(cat "/proc/$PID/cgroup" 2>/dev/null)
  echo "[$(date '+%F %T')] aid restarted OK pid=$PID cgroup=$CG" >> "$LOG_DIR/restart.log"
else
  echo "[$(date '+%F %T')] aid FAILED to restart" >> "$LOG_DIR/restart.log"
fi
