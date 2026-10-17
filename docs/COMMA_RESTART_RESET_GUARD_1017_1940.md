# comma 重启误入恢复出厂(reset) UI 事故 + 防呆加固 —— 2026-10-17 19:41:41 +0800

## 1. 事故经过（2026-10-17）
- 19:37:05 执行 `sudo systemctl restart comma`（目的：让 params.py / watchdog / diagnostics 改动对在跑进程生效）。
- comma.sh 进入 factory-reset 判定分支，打印 **`launching system reset, got taps`**，随后启动
  `python3 /usr/comma/reset --tap-reset`（AGNOS 重置确认 UI，pid 111191）。
- 结果：tmux `comma` 会话被 reset UI 占用，**manager 起不来 → UI/pandad 全无**（这也是当时"屏幕黑、没 UI"的直接原因）。
- 处置：`pkill -9 -f /usr/comma/reset`（进程已消失），comma.sh 继续走到 `exec /data/continue.sh` →
  `launch_chffrplus.sh`；19:39:23 manager 起、19:39:27 UI 起。
- **数据无损**：reset 只是"等确认"的 UI，`/data/params/d` 仍 528 键、/data 结构完好；reset 进程未做任何擦除。

## 2. 根因
`/usr/comma/comma.sh`:
```
if [ ! -f /tmp/booted ]; then
  touch /tmp/booted
  ... elif (( $(cat /sys/class/input/input2/device/touch_count) > 4 )); then $RESET --tap-reset
```
- `/tmp` 是 **tmpfs（153MB）**，`/tmp/booted` 是"本次开机已完成 reset 判定"的一次性哨兵。
- 哨兵被清掉（历史清理 /tmp 腾空间）后，任意一次**手动 restart comma** 都会被当成"开机"，
  而本机 touch_count 恒 >4 → 直接进 tap-reset 恢复出厂确认界面。
- 同理：**任何清 /tmp 的动作都会重新布下这个雷**。

## 3. 加固（已落地）
`/etc/systemd/system/comma.service.d/10-guard-tapreset.conf`（已 daemon-reload，ExecStartPre 已在 unit 中可见）：
```
[Service]
ExecStartPre=/bin/sh -c 'up=$(cut -d. -f1 /proc/uptime 2>/dev/null || echo 0); if [ "${up:-0}" -ge 300 ] && [ ! -e /data/__system_reset__ ]; then /usr/bin/touch /tmp/booted; fi'
```
- 开机早期（uptime<300s）→ 原逻辑不变，正式重置触发文件 `/data/__system_reset__` 仍有效；
- 非开机早期（=手动 restart / 崩后重启）→ 自动补 `/tmp/booted`，抑制 tap 误判。
- `systemd-analyze verify` 无告警；下次手动 restart comma 不会再掉进 reset UI。
- 注意：/etc 与 /usr 在 AGNOS OTA 换根后可能失效，届时需重装 drop-in。

## 4. 重启后核查（19:39–19:41）
| 项 | 结果 |
|---|---|
| comma.service | active (oneshot exited) |
| manager.py | 111645 / 111823（19:39:23 起）|
| UI | `openpilot.selfdrive.ui.ui` 111920 稳定运行，dmesg 无 segfault |
| pandad | 111922 + 子进程 ./pandad 1f0040000151303436363037 |
| panda | type 9(red panda v2/C3)，ver `DEV-d84b110f-DEBUG` = 子模块 HEAD d84b110fc → 固件无错配 |
| 模型缓存 | 小 `ModelManager_ModelsCache` bundles=77；大 `_Chestnut` bundles=17 extended=True → 双槽位数据齐 |
| params | /data/params/d 528 键 |
| 磁盘 | /data 30G 用 24G 剩 4.3G (85%) |
| **op-aid** | **restart comma 全过程中保持 active，pid 89932 未变 → cgroup 解耦(断联修复)生产验证通过** |
| 生效范围 | HEAD = d048c403fa(19:32)，晚于进程启动 → params.py/watchdog/diagnostics 改动已对在跑进程生效 |

## 5. 操作纪律（新增）
1. 手动重启 OP 栈前先 `touch /tmp/booted`（现已有 drop-in 自动兜底），并确认 `tmux ls` 里没有 reset UI。
2. 清理 /tmp 时**保留** `booted`；或清完立刻 `touch /tmp/booted`。
3. 若再看到 `launching system reset`，先 `pkill -f /usr/comma/reset` 再等 launch_chffrplus 接手，数据不会丢。
