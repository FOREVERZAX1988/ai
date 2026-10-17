#!/usr/bin/env bash
# migrate_aid_cgroup.sh — 一次性把 ai.aid 从 comma.service cgroup 迁到独立 unit
# op-aid.service。由 root 以 transient unit 运行(与 comma.service 不同 cgroup),
# 所以迁移期间 comma/manager 重启也不受影响。
# 用法: sudo systemd-run --unit=op-aid-migrate --on-active=120s --collect \
#         /bin/bash /data/openpilot/ai/tools/migrate_aid_cgroup.sh
set -u
LOG=/data/ai/logs/migrate_aid_cgroup.log
P='[p]ython.* -m ai\.aid'
mkdir -p /data/ai/logs
exec >>"$LOG" 2>&1
ts() { date '+%F %T'; }
cg() { local p; p=$(pgrep -f "$P" | head -1); if [ -n "${p:-}" ]; then cat "/proc/$p/cgroup" 2>/dev/null; else echo "(no aid)"; fi; }

echo "===== $(ts) migrate start; old pid(s): $(pgrep -f "$P" | tr '\n' ' ') cgroup=$(cg)"

# 1) 老 aid 必须先退出(它占着 5090, 且就在 comma.service cgroup 里)
pkill -f "$P"
for _ in $(seq 1 20); do pgrep -f "$P" >/dev/null || break; sleep 1; done
if pgrep -f "$P" >/dev/null; then
  echo "$(ts) old aid ignored SIGTERM, sending SIGKILL"
  pkill -9 -f "$P"; sleep 2
fi
echo "$(ts) old aid gone: [$(pgrep -f "$P" | tr '\n' ' ')]"

# 2) 用独立 unit 起
systemctl reset-failed op-aid 2>/dev/null
systemctl start op-aid
ok=0
for i in $(seq 1 30); do
  sleep 2
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:5090/ 2>/dev/null)
  echo "  probe $i: http=${code:-none} unit=$(systemctl is-active op-aid) cgroup=$(cg)"
  if [ "$code" = "200" ]; then ok=1; break; fi
done

# 3) 失败兜底: 退回今天的行为(comma cgroup + start_aid.sh), 保证助手一定在
if [ "$ok" != "1" ]; then
  echo "$(ts) !! op-aid not serving 200 -> fallback to legacy start (comma cgroup)"
  systemctl stop op-aid 2>/dev/null
  cd /data/openpilot || exit 1
  runuser -u comma -- setsid nohup bash ai/scripts/start_aid.sh >>/data/ai/logs/aid.log 2>&1 &
  sleep 10
  echo "$(ts) fallback http=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:5090/)"
fi

PID=$(pgrep -f "$P" | head -1)
echo "$(ts) final pid=${PID:-none} unit=$(systemctl is-active op-aid) cgroup=$(cg)"
echo "===== $(ts) migrate done"
