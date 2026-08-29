#!/usr/bin/env bash
# restart_aid.sh — 无人值守重启 ai.aid（op 助手服务）
# 用法: nohup bash restart_aid.sh [DELAY_SEC] >/dev/null 2>&1 &
# 时序: sleep DELAY → kill 旧进程 → 持久日志重启(ai/scripts/start_aid.sh) → 验证记录
set -u
DELAY="${1:-45}"
LOG_DIR=/data/ai/logs
mkdir -p "$LOG_DIR"
echo "[$(date '+%F %T')] restart scheduled (delay ${DELAY}s)" >> "$LOG_DIR/restart.log"
sleep "$DELAY"
echo "[$(date '+%F %T')] killing old ai.aid" >> "$LOG_DIR/restart.log"
pkill -f "[p]ython.* -m ai\.aid" 2>/dev/null
sleep 3
cd /data/openpilot
nohup bash ai/scripts/start_aid.sh > "$LOG_DIR/aid.log" 2>&1 &
sleep 4
if pgrep -f "[p]ython.* -m ai\.aid" >/dev/null; then
  PID=$(pgrep -f "[p]ython.* -m ai\.aid" | head -1)
  echo "[$(date '+%F %T')] aid restarted OK pid=$PID (log: $LOG_DIR/aid.log)" >> "$LOG_DIR/restart.log"
else
  echo "[$(date '+%F %T')] aid FAILED to restart" >> "$LOG_DIR/restart.log"
fi
