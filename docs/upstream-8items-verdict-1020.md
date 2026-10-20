# 上游 8 条「仍需人工合并」逐条裁决（2026-10-20）

坐标：我们 `sp-macan-test`(sync/upstream-1019) = `2aefd13325`；上游 `upstream/test` = `59efe220e6`；
merge-base `09ffdf60`。上游 23 条未 merge 里，12 条内容已一致、2 条只差 jetlink 指针、**8 条曾判为
「仍需人工合并」**（第 8 条实为 `519d9e813f` 删 numpy import，已一致）。本文把 8 条逐条啃完并留证。

结论：**8 条的上游意图全部已在我们树里**；剩下的 9 个文件差异 100% 是有意分叉（我们的调参/功能/更严的测试）。
零代码改动落地，产出是「机器可复查的分叉登记表 + 一处上游自身的测试 bug 发现」。

## 1. 逐条裁决

| 上游 commit | 主题 | 裁决 | 证据 |
|---|---|---|---|
| `52d31c1d70` | jetlink_adapter：comma 自己的 HEVC（V4L2/venus） | ✅ 接线已就位，**只有一套** | `jetlink_adapter/__init__.py:225/231/235` = 上游那 8 行原样（import hevc_venus / `make_encoder if available() else None` / `hevc_encoder=encoder`）。剩余差异是我们多带的 `KEYS.preview`(`IsOnroadPreview`) 与 `warp_path()/lossless_warp_path()` |
| `f45472b01b` | radard_dpath arena、soft hold 暂停 DM、热路径瘦身 | ✅ 三处意图都在，剩注释/调参分叉 | `radard_dpath.py:141/152` 每帧 `RadarState.new_message()`、`messaging.new_message("radarState")` 每帧；`dmonitoringd.py` 有 `soft_hold_pause_eligible()` + `soft_hold_state_packet()`；`long_mpc.py:68/345` A_CHANGE_FACTORS 预算在（我们另加 `t_follow_user_scale()`，planner 依赖它，上游没有） |
| `c41a03695d` | terminal-stop 同时满足两份契约 | ⚖️ 保留我们的实现（驾驶者实测曲线） | `stopping_controller.py` 签名已对齐上游（`update(prev_state, state, CS, ...)`）；差异是 `END_SOFT_RATE=1.0`（上游 0.4）、无前车时 `target = line` 不再切深、latch 不限 pid 状态 —— 三条都在代码里写明了理由 |
| `047f38d783` | cruise 按「注册默认值」读取 | ✅ 已全量落地 | `cruise.py:235/244` `_param()` + `params.get(key, return_default=True)`，与上游逐行同构；剩余 +20 行全是 carrot 巡航功能 |
| `279ad6f0c6` | planner 仲裁测试喂真实状态 | ✅ 我们的版本是超集 | 我们有 `_StubScc(.vision/.map)` + `_carrot_is_a_competing_target()` 源码扫描守卫 |
| `d251c69946` | carrot 工具按路径从仓库根加载 | ✅ `repo_tools.load()` 已在用 | `lead_brake_lights.py:139`、`test_signal_assist_runtime.py:6`。剩 1 行差异：我们把离线测试开关 `assist_enabled` 改成 `enable`（`assist_enabled` 已按 SignalAssistMode 单一开关退役） |
| `095085781a` | 适配c3（1419 文件巨型 squash） | ⛔ 永不 apply | 不是缺更新，是上游把整个 fork 收口成一条提交；剩余 202 文件差异 = 我们的净差异 |
| `519d9e813f` | radar 测试删无用 numpy import | ✅ 已一致 | 逐字节相同 |

## 2. 顺带发现的上游 bug（重要，防踩）

上游 tip 自己的 `test_longcontrol.py` 就挂：

```
test_stopping_decel_rate_is_smooth_while_rolling
  assert LongControlSP.stopping_decel_rate(0.1) == 0.3   # 实测 0.07
```

同一条提交 `c41a03695d` 里的曲线是 `interp(v, [0.0, 0.5, 1.5], [STOPPED_DECEL_RATE, 0.15, STOPPING_DECEL_RATE])`
（`STOPPED_DECEL_RATE=0.05`），`0.1 m/s → 0.07`，**测试和实现自相矛盾**。
验证方法（已做，跑完自动还原）：把上游 `stopping_controller.py` + `longcontrol.py` + `test_longcontrol.py`
三件套临时换成 `upstream/test` 版本跑 → **1 failed / 18 passed**；换回我们的 → 19 passed。
⇒ 重基线时**不要整体搬上游的 `test_longcontrol.py`**，否则 CI 立刻红。

## 3. 留给驾驶者的 3 个 A/B（不影响当前上路，等你回来决定）

1. **terminal stop 入口斜率**：我们 `END_SOFT_RATE=1.0` vs 上游 `0.4`（上游哲学：入口全程 <0.5 m/s³，
   乘客感觉不到第二次刹车）。判据：停车最后 2-1 km/h 的 `aEgo` 曲线 + 体感；改一处常量即可 A/B。
2. **无前车时是否允许比曲线更深**：我们现在不许（`target = line`），上游允许。
3. **AlwaysOnDM 门控**：关掉 AlwaysOnDM 时，我们的 dmonitoringd 仍然跑策略（`policy.py` 内部还按 always_on
   决定是否告警），上游两支都要求 `DM.always_on`。差异 = 关掉时是否继续更新 awareness。

## 4. 以后重基线的守则（机器可查）

- 分叉登记表：`ai/docs/upstream_divergence_registry.json`（每条记录 verdict / 我们保留什么 / 上游意图的
  **字面片段**）
- 检查器：`python3 ai/scripts/upstream_divergence_check.py --ref upstream/test`
  逐条校验 ①上游意图的字面片段是否还在我们的文件里（缺 = 上游修复被丢了）②该差异的文件是否仍与我们不同
  （变成相同 = 我们的补丁被静默覆盖）。当前 **9/9 as expected**，退出码 0。
- 重基线流程里把这条检查挂到「搬完 129 个独有文件 + 合并 params/cruise/long_mpc」之后跑一次；红了一条就
  说明有遗漏。

## 5. 本轮验证命令

```
PYTHONPATH=/data/openpilot /data/venv-jetlink/bin/python -m pytest -q \
  openpilot/selfdrive/controls/tests/test_longcontrol.py                       # 19 passed / 4 subtests
PYTHONPATH=/data/openpilot /data/venv-jetlink/bin/python -m pytest -q \
  openpilot/selfdrive/controls/lib/tests/ \
  openpilot/sunnypilot/selfdrive/controls/lib/tests/test_longitudinal_planner.py \
  openpilot/selfdrive/monitoring/test_soft_hold_pause.py \
  openpilot/selfdrive/car/tests/test_cruise_param_defaults.py \
  openpilot/sunnypilot/carrot/radar/tests/ \
  openpilot/sunnypilot/carrot/tests/test_signal_assist_runtime.py             # 43 passed / 12 subtests
/data/venv-jetlink/bin/python ai/scripts/upstream_divergence_check.py         # 9/9 as expected
```
