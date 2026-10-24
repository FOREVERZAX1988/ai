# 三分类 BSD（cp c6566c65a）+ 契约守卫 @75-79 落地（2026-10-24）

坐标：上游 `upstream/test` = `684178cb51`；我们 = `9d128aaa2b`(BSD) →
`1c5f093394`(守卫)。本轮消化登记表里最后两条「可搬」条目：`67ffbe9f03`、`1e97bf13a9`。

## 1. 变了什么（驾驶者能感知的）

| 维度 | 之前 | 现在（= 上游 cp） |
|---|---|---|
| 盲区门控 | 打灯方向 + 30–120 km/h，宽度 ≥ 3.0 m | **双侧连续监控**：只要该侧车道宽 ≥ 2.0 m 就轮流推理，不分方向、不看车速 |
| 模型 | 旧 6 列检测输出 | 352×352 三分类（资产 9.6 MB → 6.2 MB） |
| 阈值 | `OnnxBsdThreshold` 默认 45 | 默认 **94**（0–100，另有阈值相对迟滞：低于阈值 0.15 才关） |
| 新鲜度 | 一路共用时间戳 | **按侧**时间戳（`updatedMonoTimeNanosBySide`），一侧停了不再拖累另一侧 |
| carState | 只有合并后的 `left/rightBlindspot` | 多 5 个字段：`leftBlindspotOem / rightBlindspotOem / leftBlindspotOnnx / rightBlindspotOnnx / blindspotSplitSourcesValid` |

「OEM/ONNX 拆分」的意义：合并值时告警可能来自车厂 BSD 或视觉 BSD，UI/日志现在能说清是哪一路，
并且两路来源和合并值在**同一帧**写出（`card.py`），不会出现「新告警 + 来源未知」的错位帧。

## 2. 本树保留的本地增量（冲突只有 v_asm_server.py 三处）

1. **驻车关推理**（`parked_gate` / `_update_inference_gate`）：2026-10-22 实测驻车时
   `xiaoge_data` 占设备 24 % CPU。上游没有这个门，本树原样保留；`status()` 里
   `gate`（车道宽度门）与 `inferenceGate`（驻车门）并列，各自只有一个失败理由。
2. **`sm_lock`**：本树两个相机线程 + HTTP 线程共用一个 `SubMaster`，上游不加锁。新的
   `_update_vasm_gate` 采用上游语义（返回 `eligible_sides`），但 `sm` 访问仍在锁内。
3. **`_lane_change_gate` 整段退役**：打灯方向 + 30–120 km/h 的旧门随上游删除，
   `test_v_asm_parked_gate` 的 `LaneChangeGateTest` 换成 `DualSideGateTest` 锁住新契约。

## 3. opendbc 侧：cp 的 @95-99 抄不过来

cp 的 `CarState` 用 @95-99 放这五个字段（它自己的 CarState 填到了 @94）；本 fork 的 `CarState`
尾是 **@74**，capnp 不允许 ordinal 空洞——照抄会让 `capnpc` 直接
`Skipped ordinal @75` 构建失败（上游自己踩过一次）。因此：

- 我们 fork 的 opendbc：`2abfa684c` 把五个字段 append 到 **@75-79**（注释写明理由）；
- 契约守卫 `CAR_STATE_LAST_ORDINAL = 79`，五个字段逐个钉死（`1c5f093394`）。

顺带确认：本树 schema 是**运行期 `capnp.load`**，这批字段不需要 `scons` 重编，
`messaging.new_message('carState')` 立刻带新字段（实测 208 字节可写）。

## 4. 验证

```
PYTHONPATH=/data/openpilot /data/venv-jetlink/bin/python -m pytest -q \
  openpilot/sunnypilot/carrot/tests/ -k "xiaoge or yolo or asm or capnp or blindspot"
# 78 passed
python3 ai/scripts/upstream_divergence_check.py --ref upstream/test   # exit 0，4/4 一致
```

## 5. 上车要看的三件事（下车前没法验）

1. **阈值语义**：默认 94 是 cp 的「三分类置信度百分比」。市区侧后方静止车/护栏柱会不会误报，
   停车等灯时相邻车道车流会不会刷屏 —— 只看 `OnnxBsdThreshold` 一个参数即可调，不必改代码。
2. **双侧连续监控的 CPU/发热**：门从「打灯才跑」变成「两侧轮流跑」，虽然驻车门仍然挡着，
   但走走停停（5–30 km/h）会一直跑。看 `xiaoge_data` 进程 CPU 与设备温度。
3. **来源拆分字段**：`/status`（8082）里 `gate.eligibleSides` 与 `vehicleSide.*.valid` 是否
   与体感一致；`carState.blindspotSplitSourcesValid` 应恒为 true，且 OEM 侧与车机原厂提示一致。

## 6. 登记表剩余（4 条，都不是「可搬代码」）

- `eeb028a58` panda 指针（21 条 commaai/panda 同步，含 UART/safety）：**单独一轮 + 上车验**，
  与 BSD 批解耦；tizi 设备纪律是 panda 先不动。
- `ee23033248` / `e3cf1856c9`：上游 fork 的 opendbc 指针，内容（vCluRatio 等三字段 + 盲区拆分）
  我们分支早已有或本轮手工落地，**指针不搬**（搬 = 整棵 opendbc 换成上游状态）。
- `564e8e93c8`：上游自己的 rebase 基座合并（1687 文件），只承载那两个指针，永不搬。
