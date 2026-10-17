# op助手「答到一半断联」修复记录（2026-10-17）

- 记录时间：**2026-10-17 16:35 +08**
- 分支：openpilot `sp-macantest-1017` / ai `sp-macanlong-test`
- 状态：两个根因已修并提交，第三个为架构性限制（待评估），`sudo systemctl restart comma` 后对在跑进程生效

## 现象
- 会话里 assistant 回答流式输出到一半就断（content 为空或被截断），webui 卡住，有时整套栈自动重启。
- 触发时刻集中在「跑 scons 构建」或「systemctl restart comma」之后。

## 根因 1（主因，已修）：libparams_c.so 被就地重链 → SIGSEGV
- 15:27–15:28 scons 重新 link `libparams_c.so`，已 mmap 旧 inode 的进程执行到新字节 → `manager.py` 与 `athenad` 相隔 6 秒双双 SIGSEGV。
- crash 文件：`/var/crash/_data_openpilot_..._manager.py.1000.crash`、`_usr_bin_python3.12.1000.crash`；栈都落在 `std::__future_base::_State_baseV2::~_State_baseV2`（gdb 可复现；core 以 44 段 base64 分块存储，需逐行 b64decode 后拼 gzip 再解）。
- 后果：整套栈自动重启 + UI 卡 + athena ws (`wss://athena.konik.ai/ws/v2/cecfd0ca8552b71c`) 断线；客户端看到的就是「回答到一半断联」。
- 修复：`openpilot/common/params.py` 改为 dlopen 私有副本 `/data/.cache/params_lib/libparams_c-<mtime>-<size>.so`（原子 rename，保留最近 3 份，失败回退源路径）。重建库不再能破坏在跑进程。

## 根因 2（未改，架构性）：aid/webui 跑在 comma.service 的 cgroup 里
- `launch_chffrplus.sh` 的 `keep_alive aid ai/aid.py 5090` → aid 属于 comma.service cgroup。
- 因此每次 `sudo systemctl restart comma` 都会把助手进程砍掉：`/tmp/aid.log` 里 14:00:42 / 14:11:01 / 15:29:26 / 16:15:22 四次重启，会话里对应两条 assistant content 为空。
- 操作含义：重启前必须先把结论/提交/知识库写完，重启后本会话必然断开。
- 若要根治：把 aid 从 comma.service cgroup 挪到独立 systemd unit（未做）。

## 根因 3（已修）：stuck chat job watchdog 自己先死
- `ai/core/chat/jobs.py` 的 watchdog 循环里用了未定义的 `now` → 第一个 idle≥120s 的 job 就抛 `NameError`，把 watchdog task 打死（所以历史上既没 warn 也没 cancel，每个 aid 生命周期只有一条 "stuck chat job"）。
- 且工具执行期间不发事件，长 `run_shell_command` 会被误判为卡死。
- 修复：每轮 `now=int(time.time())`；逐项 `try/except` 不让 watchdog 死；新增 `inflightTools` 计数（`mark_tool_inflight`，`agent.py` 在 `_run_tool_calls` 里 +/-），工具在飞时跳过 idle/run 超时。

## 附带修复：diagnostics 的 params 检查
- `ai/core/diagnostics.py` 原来调用不存在的 `params.keys()` → 每次启动都报 11 checks 失败（实际存储健康）。改为 `all_keys()`/`get()`，现 `ok=True`；`aid.py` 改为打印失败项名字。

## 提交
- ai：`e76b43e2` fix(assistant): stop cutting streamed answers mid-flight
- openpilot 主仓：`07d103ca0f` fix(params): dlopen an immutable copy of libparams_c.so
- 本文件：ai 仓库 `docs/AID_DISCONNECT_FIX_1017.md`

## 复验（2026-10-17 16:35）
- `pytest openpilot/common/tests/test_params.py ai/core/tests/test_stuck_watchdog.py` → **18 passed in 4.08s**
  - 设备上 pytest 需手动挂 PYTHONPATH：`PYTHONPATH=/data/pytest_deps/lib:/data/openpilot/openpilot:/data/openpilot python3 -m pytest ...`（`/usr/local/venv` 里没有 pytest）
- `/data/.cache/params_lib/libparams_c-1792222119-1912144.so` 已生成，说明 dlopen 副本路径已工作。
- 生效需 `sudo systemctl restart comma`（会顺带切断当前 aid 会话）。

## 待办（下一轮）
- 4 组既有漂移测试仍未处理：`test_chestnut_parity`(2，我们 events.py 是 "now driving on small model"，上游测试期望 "small model is still available")、`test_model_manager`(1，离线重试 2≠1)、`test_queues`(2，`PolicyQueues.after_run` 签名 vs jetlink 子模块实现)、`test_warp_build`(3)。需逐条定「以我们的实现为准改测试」还是「跟齐上游」。
- aid 出 comma.service cgroup（可选，根治 restart 断联）。

## 现场排查命令
```bash
# 有没有再出现 watchdog 打死/重启
grep -n "stuck chat job" /tmp/aid.log | tail
# 在跑进程用的哪个 libparams
sudo ls -l /proc/$(pgrep -f manager.py | head -1)/maps | grep libparams
```
