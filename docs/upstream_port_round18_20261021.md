# 上游搬运 第 18 轮（2026-10-21）

基线 `sync/upstream-1019`，起点 `198d3e6076`（round 17 收口），终点 **`a828b812e8`**（opendbc 子仓 `213d3f100`）。
`git fetch upstream test` 后上游 tip 从 round 17 的 `5c2498a30e` 前进到 **`8b52c4eef5`**，即新增 4 条：
`e17b39201c`、`1c4250535e`、`fe854a7588`、`8b52c4eef5`。登记表 phase 2 仍只剩 `0facf5cf71`（agnos 腾讯镜像，skip）。

## 1. 四条逐条

| 提交 | 内容 | 处置 |
|---|---|---|
| `8b52c4eef5` | long MPC **终端级软约束**（来自 StarPilot e75470f2e）：`con_h_expr_e` + 终端 zl/Zl/Zu/zu 代价 + lh_e/uh_e/idxsh_e 边界 + 运行时 Zl 循环覆盖到 N | **原样搬** +12 行 / SConscript +2 行，**必须重生成并重编 solver** |
| `fe854a7588` | opendbc 指针 bump：`vl_all` 清理优化 | 我们的 opendbc 分支已含上游 `85095af0c` 内容，新 pin `d8d5659d05` **不是**我们分支的祖先 → 以 opendbc `213d3f100` 单提交落地等价内容 |
| `1c4250535e` | signal replay 测试改走 `repo_tools.load` 按路径加载 | 原样搬（本树 `openpilot/tools` 是常规包，`tools.signal_analysis` 永远解析不到，同因） |
| `e17b39201c` | warning-delay 测试的 car 模块来源（cereal → opendbc.car.structs） | **零工作量**：round 17 已修过同一行，实测与上游修后逐字节一致 |

## 2. `8b52c4eef5` 是这轮唯一有行车语义的改动，做法与证据

生成代码不是被参数门控的，改的是 solver 本体，所以流程是「改 `gen_long_ocp` → 重生成 → 重链接」：

1. `cd .../longitudinal_mpc_lib && python3 long_mpc.py` —— 峰值 **54.6 MB / 3.7 s / exit 0**；
   新生成 `long_constraints/long_constr_h_e_fun.c`、`long_constr_h_e_fun_jac_uxt_zt.c`，
   `acados_ocp_long.json` 里 `model/con_h_expr` 与 `model/con_h_expr_e` 长度一致（908）；
   `acados_solver_long.c` 出现 33 处 `h_e`。
2. `scons -j1 .../c_generated_code/acados_ocp_solver_pyx.so` —— 两个新 `.os` 参与 LINK，
   构建后 `MemAvailable` 1.41 GB（未触发 LMK）。
3. 生成代码是 `.gitignore` 的，所以只提交两个源文件；以后任何一次正常构建都会按 `long_mpc.py` 重生成。

### 仿真 A/B（同一套参数，0.5 s 响应滞后，脚本 `ai/tools/mpc_terminal_ab_sim.py`，
新旧两份原始输出 `ai/docs/artifacts/mpc_terminal_ab_{old,new}_20261021.json`）

| 场景 | 旧 solver | 新 solver | 差异 |
|---|---|---|---|
| follow：稳定 20 m/s，起点在期望车距后 40 m | a_sum 0.214926 | a_sum 0.214926 | **逐位相同** |
| slowdown：前车 t=20 s 起 -3 m/s²，ego 20 m/s、距 25 m | a_sum -400.472811，末车距 5.2276 m | a_sum -400.486903，末车距 5.2349 m | 末车距 +7 mm |
| approach：静止前车 60 m 外，ego 15 m/s | a_cmd 见 trace，末车距 5.1821 m | 同场景 a_cmd 最大差 0.006 m/s²，末车距 5.1903 m | 末车距 +8 mm |

即：**跟车巡航段完全不变**，只在硬减速/停车段把停位往后挪了 7–8 mm —— 这正是「终端约束以前根本没被约束、
solver 提前终止就可能越界」被修掉后的合理结果。重编后再跑一次，trace 逐位复现（`new.json == new2.json`）。

## 3. 验证数字

| 套件 | 结果 |
|---|---|
| `pytest openpilot/selfdrive/controls/lib/tests` | **266 passed, 1 skipped**（= round 17 基线） |
| `pytest openpilot/sunnypilot/selfdrive/controls` | **936 passed, 8 failed**（= 基线同一批 8 条，换 solver 前后一致，均不在 MPC 路径） |
| `macan_mlb` + `radar_fusion` + `vcruise_pcm_set_speed` | **59 passed**（43 + 10 + 6） |
| `pytest opendbc/can/tests` | **50 passed, 590 subtests**（含上游新增 `TestOnlyPopulatedListsClear`） |
| `pytest opendbc/can/tests/test_packer_parser.py` | 17 passed |
| `tools/signal_analysis/test_signal_assist_planner.py` | 收集期不再炸；**4 skipped 且带原因** |

`tools/signal_analysis` 那 4 条 skip 不是本轮引入：harness 按 cp 的 `CarrotPlanner` 形状 exec，本树 planner 还没有
`signal_observation/signal_context` 钩子，`replay_filters` 里也没有 `MyMovingAverage`。要真跑起来得先把 cp 的信号钩子搬进
本树 planner —— 已登记待办，不是「测试静默通过」。

## 4. Macan 适配完好性

本轮只碰了 long MPC 生成数学与 opendbc 的 CAN 解析清理，两者都不改车型定义。Macan 三套件 59 passed，
`PORSCHE_MACAN_MK1` 的 brand/转向类型/安全模型未变。新 solver 会在下一次 plannerd 启动时加载
（当前 offroad，plannerd 未运行，磁盘上已是 23:32 的新 `.so`）。

## 5. 下一轮

上游代码层依然清零（只剩 agnos skip）。剩下的都在驾驶者侧：
①重启后确认 plannerd 载入新 solver（`/proc/<plannerd>/maps` 里 `libacados_ocp_solver_long.so` 非 deleted 且 mtime 23:32）；
②`EnforceTorqueControl` 现值是否保留；③原有路试项（terminal stop 斜率、AlwaysOnDM、视觉限速、天气、NNFF 灰化）；
④panda 指针差 21 条属独立一轮；⑤以 `upstream/test` 重基线仍是最大的一块。
