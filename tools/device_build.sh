#!/bin/bash
# 在 comma 设备上安全编译 openpilot。
#
# 为什么需要这个脚本（2026-11-01 事故）：
#   comma 3 只有 3.6GB 内存，openpilot 运行时占掉 2.7GB。直接 `scons -j4` 会在编
#   locationd 的 live.os 这类大文件时被 OOM killer 杀掉，**正在写的 .so 会被截断成
#   0 字节留在原地**。更坑的是 scons 默认缓存 /data/scons_cache 会把这个坏产物存进去，
#   之后 `scons` 报 "Retrieved ... from cache" 并报 done building targets —— 看着成功，
#   实际 ipc_pyx.so 还是 0 字节，重启后 manager 直接
#   `ImportError: .../msgq/ipc_pyx.so: file too short`，UI 起不来。
#
# 用法（在设备上）：
#   bash /data/tools/device_build.sh
#   # 编完自行 `sudo systemctl reboot`，或加 --reboot 让脚本代劳
#
# 关键点：done building targets 不等于产物有效，必须查 0 字节。
set -u
cd /data/openpilot || { echo "不在 /data/openpilot"; exit 1; }
export PATH=/usr/local/venv/bin:$PATH

JOBS="${JOBS:-2}"   # -j4 在这台设备上必 OOM，别改大

echo "[1/4] 停 comma 释放内存（运行时占 ~2.7GB）"
sudo systemctl stop comma 2>/dev/null || true
sleep 2
free -m | sed -n 2p

echo "[2/4] 清理上次 OOM 留下的 0 字节产物"
STALE=$(find . -name "*.so" -size 0 -not -path "./.git/*" 2>/dev/null)
if [ -n "$STALE" ]; then
  echo "$STALE"
  echo "$STALE" | while read -r f; do rm -f "$f"; done
  echo "已删除，本次将强制绕过缓存重编"
  FORCE_NOCACHE=1
else
  echo "无残留"
  FORCE_NOCACHE=0
fi

build() {
  if [ "$1" = "1" ]; then
    echo "[3/4] 编译 (-j$JOBS, --cache-disable)"
    scons --cache-disable -j"$JOBS" 2>&1 | tail -8
  else
    echo "[3/4] 编译 (-j$JOBS)"
    scons -j"$JOBS" 2>&1 | tail -8
  fi
}
build "$FORCE_NOCACHE"

echo "[4/4] 校验产物（这是本脚本存在的理由）"
BAD=$(find . -name "*.so" -size 0 -not -path "./.git/*" 2>/dev/null)
if [ -n "$BAD" ]; then
  echo "❌ 仍有 0 字节 .so（大概率又 OOM 了）："
  echo "$BAD"
  echo "→ 再跑一次本脚本；若反复出现，改用 JOBS=1"
  exit 1
fi
# 关键 .so 必须存在且非空，否则 manager/cereal 起不来
for f in msgq/ipc_pyx.so msgq_repo/msgq/ipc_pyx.so; do
  if [ ! -s "$f" ]; then echo "❌ 缺失或为空: $f"; exit 1; fi
done
echo "✅ 产物正常："
ls -la msgq/ipc_pyx.so msgq_repo/msgq/ipc_pyx.so | awk '{print "   " $5, $9}'

if [ "${1:-}" = "--reboot" ]; then
  echo "→ 重启"
  sudo systemctl reboot
else
  echo "→ 完成。确认无误后 sudo systemctl reboot"
fi
