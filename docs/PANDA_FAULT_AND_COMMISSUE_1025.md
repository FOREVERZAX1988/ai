# 「panda 全程报错」到底是什么：faultTemp/registerDivergent 定案 + commIssue 证据收敛

时间：2026-10-25　设备：comma-a821bfb2（H7 内置 panda，type `tres`，FW `DEV-d84b110f-DEBUG`）
路线：`000000ad--f4fe6e6d73--*`（18 段，10-24 19:37→19:54）

## 1) 先纠正我自己的说法

我之前说「panda 全程报错」是**错的表述**。真实的是：

| 项目 | 实测（全 18 段逐段统计） | 结论 |
|---|---|---|
| `pandaStates.faultStatus` | 每段每一帧都是 `faultTemp` | 临时故障，非永久 |
| `faults` | 只有 `registerDivergent`（bit18），别无其他 | 单一故障位 |
| `canState0/1/2.busOff` | 0 | CAN 总线没掉 |
| `busOffCnt` / `totalTxLostCnt` | 0 / 仅第 17 段 1（收车熄火尾巴，ign=false） | TX 全程正常 |
| `safetyRxInvalid` / `safetyTxBlocked` | 0 / 仅第 0 段 14 帧（elm327 启动期，还没切 safety） | 安全校验没拦东西 |
| `safetyModel` | 从第 1 段起全程 `volkswagenMlb` | 车型安全模型正确 |
| `carControl.enabled` | 第 8/9/10/11/12/14 段共启用了 906+5683+2573+6007+1625+3959+21+2961 帧 | **确实在控车** |

所以你说的对：**如果 panda 真的全程报错，你根本控不了车。** 控车正常，是因为这个故障位跟控车无关。

## 2) `registerDivergent` 为什么会一直挂着

- 全仓 grep：`faultStatus` 在 openpilot / sunnypilot / webui 里**零消费者**，唯一读它的是我们自己的
  `ai/selfdrive/state.py`（诊断快照）。它不参与 engagement、不参与 lateral/longitudinal 允许判断、不拦 TX。
- panda 固件里 `board/drivers/registers.h::check_registers()` 只在"寄存器回读值 ≠ 我们写下去的值"时
  `fault_occurred(FAULT_REGISTER_DIVERGENT)`，**没有对应的 `fault_recovered()`** → 一旦置位，
  整个上电周期都不会自动清除。所以"全程挂着"= 「这一开机里至少有一次回读不符」，不是「每帧都在坏」。
- `board/sys/sys.h`：`PERMANENT_FAULTS 0U` → 所有故障都只能是 TEMPORARY，即 `faultTemp` 是这类故障的天花板。

### 时间线证据（说明是「某一次开机」才有）

| 路线 | 首帧 pandaState |
|---|---|
| `000000ac--a82a514e9d--0/1`（10-24 18:00，同固件同车型） | `none`, faults=[] |
| `000000ad--f4fe6e6d73--*`（10-24 19:37 起，校准+重启之后） | `faultTemp`, faults=[`registerDivergent`] |

→ 18:01 那个上电周期干净，19:37 这个上电周期置位。这是**开机期的竞态**，不是随行驶出现的问题。
pandad 每次启动会 `Resetting panda`（swaglog 可见），panda 软复位后 `init_registers()` 重建寄存器表，
如果某次上电时有一次 `register_set()` 写下去的值在硬件侧被合法改写（例如写下去后硬件自己清位/改位），
这一次检查就把它记成 divergent 并一直挂着。

### 最可能的那个寄存器（还没法在设备上直接指认）

- H7 路径里唯一被上游自己注明"写入会静默失败"的就是 `PWR->CR3`：
  `board/stm32h7/clock.h` 注释原文：bootstub 先写、app 再调 `clock_init` 时 **CR3 写入会静默失败**。
  而它用 `register_set(&(PWR->CR3), PWR_CR3_LDOEN|SMPSEN, 0xFU)` 把 bit0..3 全纳入 check_mask。
  若 bootstub 留下的 CR3[3:0] 与 app 这次想写的值不同 → 回读永远不符 → 永久挂 `registerDivergent`。
- 次要候选：`RCC->CR` 的 `HSEON/PLLON`（起振失败会被硬件自动清）、`SPI4->CR1/CFG1` 的 enable 位。
- 要真正指认到地址，必须烧一版 `DEBUG_FAULTS` 固件读串口打印（`registers.h` 里会打出地址/期望值/实际值/掩码）。
  这需要拆台上车前先备好，**目前不值得为一个不影响控车的标志位去刷 panda**。

## 3) 结论与动作

- panda 侧：**不改固件**。理由：故障位无消费者、TX/RX/安全校验全正常、任何 panda 源码改动都会让 pandad
  在下次启动时按签名不匹配重刷内置 H7 panda（`pandad.flash_panda`），收益为零、风险非零。
- 如果哪天真要清掉它：一行语义修正即可 —— 把硬件自管理的位从 check_mask 里摘掉（`PWR->CR3` 改成
  不纳入跟踪，或给 `register_map` 加 `register_forget()`），台架刷写完用 `tests/h7_binary_parity.sh` 对照。
- 「进程间通讯错误」与它无关，见下条。

## 4) commIssue 的日志证据收敛（已落地）

`selfdrived.py` 以前把 `self.sm.valid/alive/freq_ok` 里**所有** False 的服务名都写进 `cloudlog.event("commIssue")`，
而 `all_checks()` 只走 `static_freq_services` 减掉三张 ignore 名单 —— 于是 on-demand 服务
（`alertDebug`、`lateralManeuverPlan`、`uiDebug`、`operatingSystemLog`…）这些**永远不可能 valid** 的名字
反复被当成证据，把每次诊断都带偏。

落地：抽出 `comm_issue_checked_services(sm)`（= `all_checks()` 真正走的集合），cloudlog 只报这个集合里的服务；
新增 `openpilot/selfdrive/selfdrived/tests/test_comm_issue_services.py`（3 条：ignore 名单不出现在证据里、
on-demand 服务永不被点名、范围不会比 static_freq_services 更大）。

路线统计（`000000ad--f4fe6e6d73--*` 全 18 段 onroadEvents）：`commIssue` 38 条帧、`commIssueAvgFreq` 9 条帧
——事件是"存在即记录"的逐帧条目，38 帧对应的实际发作次数远小于 38（约 5 次），这解释了你"感觉不止 5 次"的对不上：
数字口径不同（帧 vs 次），不是漏报。

## 5) 「轨迹窄/断掉」这条：`_get_path_half_width` 不用动

- 本地 `sunnypilot/onroad/model_renderer.py::_get_path_half_width` 与上游 `upstream/test` **逐字节相同**：
  `0.9 if lateral active else 0.40`，外面套 `FirstOrderFilter(0.9, 0.1)` 防跳变。所以"要不要改回 0.9"是伪命题，本来就是 0.9。
- 车宽不参与绘制：半宽是常量，`CarParams` 里没有、也不需要 Macan 车宽参数。
- 模型路径视野实测健康（第 8 段 1200 帧 modelV2）：path 末端 x 中位数 71.3 m、p75 95.9 m、max 119.7 m，
  `MAX_DRAW_DISTANCE=100` 才会截。所以"带子只画一小段"不是模型路径被截断。
- 真正让带子在前车前面提前收尾的是**上游自身**的 `_update_model`：
  `lead_d = lead.dRel * 2.0; max_distance = clip(lead_d - min(lead_d*0.35, 10.0), 0, max_distance)`
  —— 有前车时带子按设计就是提前 ~35%（最多提前 10 m）收在前车之前。这是上游行为，不是我们移植引入的。
