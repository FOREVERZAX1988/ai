# 上游 test 第 11 轮 — 限速突降的舒适松弛 + Safe Mode 的 stock 语义（2026-10-21）

范围：`dbe9c7c52c`。这是 StarPilot 差距清单里的第 9 条，加上作者在真机上核对元数据时
发现的三处 Safe Mode 问题。

## 一、限速突降不再阶跃

车正在稳定跟随前车时，限速牌突然大幅下降（比如 100 → 60），SLA 原来会把目标速度**一步**压下去，
车就被要求瞬间多减速。新模块 `speed_limit/lead_drop_relaxation.py` 在**状态机之后**把这个目标
按舒适速率放下去 —— 放在状态机之后是有意的：事件仍然播报真实限速，被软化的只是喂给求解器的目标。

否决条件（设计边界，不是可调项）：前车必须是可信的持续前车、车距与时距下限、前车制动与接近速度上限、
驾驶者接管、最低车速。默认关（`SlcLeadDropRelaxationEnabled=0`）。

## 二、Safe Mode 的三处修正

1. **转向类旋钮改为「删除」而不是写 0.0**。`SteerDelay/SteerFriction/SteerKP/SteerLatAccel/SteerRatio`
   都是「0.0 表示未设置」的参数，每个消费者在键缺失时回落到自己的原厂值；写一个 0.0 进去，
   FLM 工作区那侧会读成「存在但非法」。所以 `SAFE_MODE_REMOVE_KEYS` 直接删键。
2. **删掉 5 个死的 `*Stock` 影子键**。旋钮要回到的原厂值来自 `getKeyStockValue`（注册默认值的回落），
   不是另存一份 param。
3. `LongitudinalPersonality` 的 `"1"` 是 **standard**，注释原来写成 relaxed。

## 三、本树的两处加固

- 两处开关读改成 `param_read.read_bool`。第一遍跑测试时 `controls` 目录直接红了 11 条：键还没编进
  `libparams_c.so`，`get_bool` 抛 `UnknownKeyName`，plannerd 直接死。改走 `read_bool` 后回到 8 条既有红。
  这条是本轮唯一一次「先写代码后重建库」踩到的坑，值得记着。
- Developer 页加了 **Comfort Speed Limit Drop** 开关。它不是 `Carrot*` 键，`audit_ui_reach.py` 的
  `NAME_RE` 根本看不到它 —— 没有这一行，这条松弛就会「在控制路径上跑、屏幕上没有任何开关」。

## 验证

- 新增 `test_lead_drop_relaxation.py`：与全套 speed_limit 测试一起 **272 passed**
- `openpilot/common/tests` + `sunnypilot/common/tests`：**165 passed**（含 Safe Mode 真库用例）
- `controls` 目录：**879 passed / 8 failed**；同一批 8 条在 `HEAD` 上是 **852 passed / 8 failed**，
  逐条一致（既有夹具缺口，不是本轮引入）
- 库重建：`scons -j1 openpilot/common/libparams_c.so`，offroad、`MemAvailable 1.43 GB`、未触发 LMK；
  `SlcLeadDropRelaxationEnabled` type=BOOL 默认 False，`SteerRatioStock`/`SteerKPStock` 实测 `UnknownKeyName`
- `ruff`：改动文件 0 新增（planner 的 1 条 F401 与 `HEAD` 一致）
- `upstream_divergence_check.py --side worktree --pending-only`：phase 2 **3/3**、phase 3 **4/4**

## 下一步（items 剩 3 条，全是 eval）

- `d81eec5899` 视觉限速 daemon（2883 行 + 22MB onnx，需 LFS/分块推，新增常驻进程）
- `63a6f3211b` NNFF 横向神经网络前馈（127 文件）
- `d4136d1df0` 把视觉限速喂进限速解析器 —— **依赖 `d81eec5899`**

这三条都不是「静默搬」的量级：前两条要驾驶者先拍板「要不要为它多一个常驻进程 / 多 22MB」，
第三条必须等第一条。这也是本轮把登记表从 8 条清到 3 条 eval 的边界。
