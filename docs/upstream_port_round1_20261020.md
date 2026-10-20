# 上游未移植清单第一轮：搬三条（2026-10-20 晚）

按 `upstream_pending_port_20261020.md` §5 的协议逐条走：**一次只搬一个 group，搬完让探针翻
`DRIFT`，再改表**。本轮啃的是清单里三条自带「建议搬」结论的（另加一条它们连带触发的收尾）：

| group | 上游 commit | 我们的提交 | 结果 |
|---|---|---|---|
| carrot/signal | `0429a86b67` 红灯停止记忆过 5 km/h 退役 | `c392fb4e6c` | 搬完 |
| system/proclog | `0fa33738ca` 进程缓存按 starttime 身份索引 + `gc.freeze()` | `0c858ccab4` | 搬完 |
| selfdrived/nnff | `4f4256c37b` torqueNNLoad 一次性播报 + 删 `_notify_cwp` | `d337e96239` | 搬完 |
| tests/device-routing | `02cd2d1b5b` NNFF 两处期望值修正 | `d337e96239` | 搬完（零分叉） |
| tests/device-routing | `c2df04b193` 测试门控（CarrotPlanner 改名 / smaps cycle） | `6378ec4aff` | 搬完（零分叉，见下「部分」） |

清单 35 条 → **31 条**（`upstream_pending_port.items`），另有 `ported` 段留档 5 条。

## 1. 三条各自搬了什么（给以后用）

### `0429a86b67` carrot/signal —— 真 bug，不是整理
两套信号辅助守卫（`SignalAssist` / `SignalStartGuard`）**只在静止时上闩、没有速度上限**。
跟车时有效 veto 被逐帧旁路，但内部 latch 还上着 → 前车在高速消失时红灯 veto 被重新按上来，
而无条件写 `v_cruise` / `stop_dist` / `xState=e2eStopped`。上游的记录里有一次实测：
76.5 km/h、plan target −4.4967 m/s²、实测 −3.6156 m/s²，而前 6.45 s 没有任何新信号航迹。

搬运内容（`departed_signal_stop()` = |v| > 5 km/h）：
- `SignalAssist.update`：在 `_observe` **之前**退役 latch（时钟回滚也不再返还 hold）
- `SignalStartGuard`：在回滚检查**之前**退役 latch
- `CarrotPlanner._retire_departed_signal_stop()` + `_signal_stop_owned`：退役时带走它注入的
  `e2eStopped`；驾驶员显式停车（`_user_stop_distance >= 0`）和 stay-stop 保留所有权
- 末级输出门：5 km/h 以上只释放「信号 veto」，**不动** MPC / 模型障碍 / 前车已经要求的制动

`SignalAssistMode=0` 时整条链休眠 —— 这台车现在的设置下不会改变日常体感。

### `0fa33738ca` system/proclog
`_get_proc_extra` / `_get_smaps_cached` 只按 PID（加名字兜底）缓存，而 `_parse_proc_stat`
早就有 `starttime`。后果：短命 helper 常驻到守护进程死亡；PID 复用报出上一个进程的
argv/页数。修法=两个缓存都按 starttime 身份索引、每轮 `_prune_proc_cache()`、建任何守护
资源之前 `gc.freeze()`（继承来的 manager 堆只被 GC 走过一遍就会变成私有页）。

### `4f4256c37b` selfdrived/nnff
- `torqueNNLoad @105`（`cereal/log.capnp`）：上电后一次性播报「加载的是哪个 NNFF 扭矩模型
  卡片」，型号来自 `CarParamsSP`（不是 `CarParams`），模糊指纹匹配到的替代品会写「（替代模型）」。
- `Events.bind_nnff_notice()` 按**实例**重绑 `EVENTS`（`EVENTS | {...}`），`get_events_mapping()`
  返 `self._events_mapping` —— 每帧 `contains()`/`create_alerts()` 不复制字典。
- `SelfdriveD.update_nnff_alert()`：`frame >= 550`（11 s）且 `frame % 50 == 0` 起按 2 Hz 轮询，
  要求已初始化、非 passive、deviceState.started、CAN 正常、`all_checks()`、无 `NO_ENTRY`、
  `AM.current_alert is EmptyAlert`、NNLC 参数已开、型号非空非 `MOCK`。
- `auto_update`：删 `_notify_cwp` / `NOTIFY_TIMEOUT` / `_diff_stats` 和挂空的 `cweb_push` 导入。

## 2. 上游自己写错、我们被迫修的测试（重要）

这三条的上游测试**在上游从来没真正跑过**（`cereal`/`msgq` 没编 → 全 skip），所以里面藏着
四个 bug。前三个我们独立发现后，上游 5 分钟内也发了同样的修正（`c2df04b193` / `02cd2d1b5b`），
于是我们**改用上游版本**，两个文件现在与 `upstream/test` 逐字节一致：

| 位置 | 上游原样 | 后果 |
|---|---|---|
| `test_signal_departure.py` 导入 | `from ... import CarrotPilot` | 本树类名是 `CarrotPlanner` → 22 例里 11 例静默 skip |
| `test_proclog_identity.py` smaps 用例 | 不推进 `_smaps_cycle` | cycle 0 按设计无条件刷新 → 「identity 不变=缓存命中」必失败 |
| `test_nnff_notice.py` alert_type | `"torqueNNLoad/PERMANENT"` | 本树 alert_type 用 EventType 的**值**（`permanent`）→ 断言必失败 |
| `test_nnff_notice.py` 启动窗 | `frame=550` 断言「不播」 | 与自己的 `frame < 550` 门相反；550 就是第一个可播帧 |

第四个我们没跟上游对齐（**上游到 817f4a78c2 都没改**，属于上游漏改，我们保留自己的修法）：
`4f4256c37b` 删了 `_notify_cwp`，但 `carrot/server/tests/test_auto_update.py` 与
`test_git_config.py` 还在 `monkeypatch.setattr(auto_update, "_notify_cwp", ...)`
（默认 `raising=True` → `AttributeError`）。实测 `test_auto_update` 1 failed，删掉 hook 后
136 passed。**重基线时如果整目录用上游版，这两处会立刻炸。**

## 3. 验证（本机实测，不是「应该通过」）

```
test_signal_departure.py            22 passed / 0 skipped
test_proclog_identity.py             8 passed / 0 skipped
test_nnff_notice.py                 20 passed / 0 skipped
test_signal_stop_prepare_runtime    12 passed
carrot/tests                       669 passed
selfdrived/tests                    32 passed
selfdrived + sunnypilot selfdrived   77 passed
carrot/server/tests                136 passed / 48 skipped
openpilot/system/tests       4 failed + 5 errors —— git stash 前后对照确认既有环境问题
ruff                               干净（selfdrived.py:207 is_remote 未使用是本次之前就有）
```
`openpilot/system/tests` 那 4+5 条是 `test_launch_boot_bootstrap.py`（安装器模板）与
`test_logmessaged.py::test_big_log`，与 proclogd 无关，用 `git stash push -u` 前后各跑一次
对比确认。

## 4. 设备侧还没做的（别当已验收）

1. **capnp 要重编**：`log.capnp` 加了 `torqueNNLoad @105`，设备上要过一次 SCons 才会出现在
   `cereal` 的 Python 绑定里（本机 pycapnp 动态加载已验证 =105）。
2. **NNFF 播报只能路试看**：`selfdrived` 是 `only_onroad`，且要 frame ≥ 550（约 11 s）之后，
   短途可能一次都看不到。要看的是「NNFF 扭矩模型已加载」+ 型号（替代品带「（替代模型）」）。
3. **红灯 latch 退役只能路试看**：`SignalAssistMode > 0` 才生效；观察点是「跟车绕开后前车
   消失，车是否还会突然掉到 e2eStopped / 掉 v_cruise」。
4. **`c2df04b193` 的后半没搬**：`xiaoge/v_asm_server.py` 的 `MIN_LANE_INTERVAL_MS=600`
   + `last_inference_ms * 1.15` 反压（上游实测 SDM845 车道模型 Gold ~421 ms / Silver
   941–1104 ms，默认 400 ms 会背靠背推理、GIL 饿死其它线程 → 下游「model lagging」）。
   仍以独立条目留在清单里，代价是 BSD 车道频率从 ~2.5 Hz 降到 1 Hz，要驾驶者拍板。
5. **`43ba6fa17b` 的文档战绩**（上游设备 614/614）等我们自己在设备上跑出 skip=0 再补。

## 5. 重基线时怎么用这一页

1. `python3 ai/scripts/upstream_divergence_check.py` 必须 `phase 0 OK` / `phase 1 20/20` /
   `phase 2 31/31`。任何 `DRIFT` 先改表再说。
2. 本轮新增的 11 条 phase 1 条目里，**`expect_diff: false` 的六条**
   （`signal_assist.py`、`signal_start_guard.py`、`proclogd.py`、
   `test_proclog_identity.py`、`test_signal_departure.py`、`auto_update.py`）现在是逐字节一致的：
   它们存在的意义是「被换回旧版就 FAIL」，不是「我们在这上面有分叉」。
3. `carrot_functions.py` / `events.py` / `selfdrived.py` / `log.capnp` 仍是 `expect_diff: true`：
   前三个带本树自己的内容，`log.capnp` 只差 `ModelDataV2.meta.laneWidthLeft/Right`
   （属未移植 `bde651b930`）。

## 6. 部到位了吗（推送 / CI / 上车检查）

- 父仓 `44aad7483b` 已推 `origin/sp-macan-test` 与 `origin/sync/upstream-1019`（两分支 tip 相同，
  `git ls-remote` 核对过）；ai 子仓 `df1f6ece` 已推 `origin/sp-macan-test`。
- **这个仓没有针对 `sp-macan-test` 的 workflow**：GitHub API 查该分支历史 workflow_runs = 0，
  两个新 SHA 也没有 run 生成。所以这轮没有 CI 可等（需要 CI 的是 jetlink 仓，本轮没碰它，
  `jetlink_repo` 指针仍是 `6186a4b`＝CI 绿的那版）。
- 磁盘上已经是新代码，但**进程里跑的还是旧字节码**：`proclogd` / `selfdrived` / `auto_update`
  都要等一次 `sudo systemctl restart comma`（或重启设备）才生效。本次没有动任何服务。
- 六个模块的 import + `py_compile` 已在设备本机（`PYTHONPATH=/data/openpilot`，
  `/data/venv-jetlink/bin/python`）过一遍，全部通过。
- 上车后看三件事：
  1. `cereal` 的 Python 绑定是 pycapnp 运行时加载 `.capnp`，`EventName.torqueNNLoad` 立即可用
     （本机已验证 = 105）；C++ 侧要等下一次 SCons 才会带这个枚举，但它只有 Python 用，不阻塞。
  2. NNFF 播报：行车约 11 s 后应弹一次「NNFF 扭矩模型已加载」+ 型号；模糊匹配的机型带
     「（替代模型）」。只有一次，且要 `NeuralNetworkLateralControl` 参数为开、型号非 MOCK。
  3. proclogd：`proclog` 消息里每条进程应带 `starttime`，内存曲线不该出现「同一个 PID 换了
     argv」的串数；`gc.freeze()` 在 `main()` 里、建 `PubMaster` 之前。
