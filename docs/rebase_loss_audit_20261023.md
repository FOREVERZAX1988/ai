# 10-22「重排」吞改动的复盘与审计方法（2026-10-23 21:5x）

## 一句话
10-22 的 `7399ffe498 port(round 23): 以上游 test 9e002fb2 为底重排 sp-macan-test2`
（以及同一批的 `2e36dcdd71 / d54a20b452 / 0e3df03d1a`）在多个文件上直接取了上游版本，
把本地改动**整段吞掉**，但把对应的测试留在了树里 —— 于是 github 上看着绿、车机上静默降级。
本次一共找回 4 处，其中 2 处是运行期可见的。

## 怎么发现的（可复用）
1. 跑本地区域的**全量测试**，不要只跑改动文件：
   `python3 -m pytest openpilot/sunnypilot/carrot/tests openpilot/sunnypilot/selfdrive/controls/lib/speed_limit -q`
   → 6 failed（collection error 2 条：`PARKED_SPEED_MPS`、`parse_param_types` 导入不到）
2. 跑分叉登记表检查器：`ai/scripts/upstream_divergence_check.py --side worktree`
   → phase 1 报 4 条 `WARN … expected to differ from upstream but is identical (patch lost?)`
   和 2 条 `FAIL … upstream intent missing`
3. 对每个可疑文件做**三代对比**（这是最有效的一步）：
   ```
   git show d1155add38:<path> | wc -l          # 重排前的本地版本
   git diff d1155add38:<path> HEAD:<path>      # 差到哪去（少的那半就是被吞的改动）
   git log -S "<只可能在本地出现的符号>" --full-history -- <path>
   ```
   注意 `git log -S` 在合并被简化时会漏掉删除，必须加 `--full-history`。
4. 回贴用 `git show <原提交> -- <path> > /tmp/x.patch && git apply -3 /tmp/x.patch`（干净套用，无冲突）。

## 本次找回的 4 处
| 文件 | 丢的是什么 | 后果 | 回贴自 |
|---|---|---|---|
| `sunnypilot/carrot/xiaoge/v_asm_server.py` | `parked_gate()` / `PARKED_SPEED_MPS=0.3` / `sm_lock` / `inferenceGate` / Y 平面在门后 | 停车时 xiaoge 继续跑 ONNX（实测全机 24% CPU），停车时 UI 抢不到核 | `57a0a19f0c` |
| `sunnypilot/carrot/tests/audit_param_consistency.py` | `parse_param_types()` | `test_param_types` 直接 ImportError | `416b8a1964` |
| `selfdrive/ui/sunnypilot/layouts/settings/carrot_tuning_items.py` | 22 行车机设置控件（含 14 个控制路径开关）+ `feature_support.ui_enabled()` 门控 + import | 车机上根本调不到这些开关；`audit_ui_reach` 从 19/0 变成 5/14 | `d1155add38`（pre-rebase blob） |
| `sunnypilot/carrot/web_settings.py` | `_KEYWORD_ARG_RE` 的单双引号支持、`collect()` 的 bytes→str | 8088 网页面板把所有键塞进「other」，分页全丢 | `d1155add38` |

连带修掉的一条**上游测试与本分支语义冲突**：`test_signal_assist_runtime.py` 写的是已退役的
legacy 文件 `/data/signal-color-shadow/assist_enabled`，本分支 `requested()` 对该名字一律 False
（单开关是 `SignalAssistMode`）。改成普通文件 flag 后继续固定「两个显式开关」的契约。

## 验证
- `carrot/tests + speed_limit + test_vision_limit_threshold_row` = **975 passed, 0 failed**
- `docs/carrot_no_ui_switches.md` 重新生成：19 个控制开关 **19 个有 UI 入口，0 个没有**

## 还没查完的（下次别再当新问题重开）
- 剩下 4 条 `WARN … identical (patch lost?)`：`dmonitoringd.py`、`radar/radard_dpath.py`、
  `controls/tests/test_longcontrol.py`。三条重排前后的差异都很小（2/-5、8/-11、21/-49 行），
  既可能是真丢，也可能是登记表里 `expect_diff: true` 早就过时 —— 下一次要么证伪（`git diff
  d1155add38:<path> HEAD:<path>` 里没有本地意图）、要么回贴，然后改登记表。
  两条 `FAIL … upstream intent missing`（`jetlink_adapter/__init__.py` 的 `hevc_venus`、
  `test_longitudinal_planner.py` 的 carrot 竞争目标断言）属于「上游新意图还没并进我们的版本」，不是丢失。
- 没做全树扫描。建议下一次的机械护栏：把 `upstream_divergence_check.py` 的 phase 1 从
  「registry 里登记过的文件」扩到「`git diff d1155add38 --name-only` 的全部文件」，
  这样重排吞改动会在 CI 里直接报出来，而不是等测试红。
