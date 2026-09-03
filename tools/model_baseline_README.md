# model_baseline.py — 模型行为基线评测

切换模型后用**同一路线**录route → 跑本工具 → 对比JSON，客观判断模型差异，
区分"该模型自己解决的"与"仍需代码适配的"。

## 用法
```
python3 ai/tools/model_baseline.py                 # 最近route(rlog全量,含lead指标,慢)
python3 ai/tools/model_baseline.py 0000006c        # 指定route
python3 ai/tools/model_baseline.py 0000006c --qlog # 快速版(20-40s扫全route, 无lead指标)
python3 ai/tools/model_baseline.py 0000006c --segs 5
```
结果自动存 `ai/tools/model_baseline_results/{route}_{模型}_{时间}.json`（自带模型名与时间戳）。

## 四个指标（衡量"模型给代码的输入质量"，与车型执行层无关）
| 指标 | 来源 | 含义 | 大=什么 |
|------|------|------|---------|
| vT跳>0.5 / vTP95 | longitudinalPlanSP.vTarget | 曲率限速目标逐帧跳变 | 模型路径曲率噪声大→SCC弯道减速晃 |
| aT跳>0.5 / aTmax | longitudinalPlan.aTarget | 减速命令帧间阶跃 | planner输出阶跃→verz桥要柔化的负担 |
| lead翻 / lead跳 | radarState.leadOne | present翻转 + dRel跳变(>5m) | 视觉lead不稳→雷达融合负担(仅rlog) |
| sccV% | plan源为sccVision占比 | 弯道限速激活时间比例 | 模型曲率触发SCC限速的频繁度 |

## 对比流程（建议固定路线）
1. 固定一条含"弯道+跟车+高速"的路线（如006c那段的GPS弯道）
2. 模型A（如CD210）跑完 → `model_baseline.py <route> --qlog`
3. 切模型B → 同路线再录 → 再跑一次
4. 对比两次JSON：vT跳↓=模型曲率预测变稳(代码侧曲率补偿可考虑放松)；
   aT跳↓=planner命令更平滑(verz桥负担小)；lead指标(需rlog)↓=视觉lead更稳(融合权重可复查)

## 注意
- qlog模式无radarState → lead翻/跳恒0（快速对比用）；完整对比建议 rlog（每段约20-60s，全route 27段约10分钟）
- 段时长 = plan消息活动跨度（自动剔除熄火gap）
- 模型名显示逻辑：有 ActiveBundle=自定义激活模型名；无 = default(stock)（固件默认）
