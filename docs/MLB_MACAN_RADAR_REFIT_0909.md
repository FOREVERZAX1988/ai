# Macan 雷达标定 —— 0909 高速段重拟合校正（推翻了低速-only 旧结论）

状态：2026-09-09 实测完成。**证明 route 0004 存在真实高速跟车段**（旧扫描误判为全低速），
据此重拟合 `_macan_abstands_t`，确认旧表系统性偏低 ~17%。

## 一、route 0004 高速段位置（重要修正）
旧文档（MLB_MACAN_RADAR_CANONLY_CALIB.md）称"0004 全 59 段为低速城市路，maxV 最高 26.3 km/h"——**错误**。

本轮用 qlog vEgo + rlog ESP_03 轮速报文双重证实，0004 高速段在 **seg19~seg26**（总时间 ~1140s~1620s，覆盖用户所说 1222s~1600s）：

| seg | 最大 vEgo (km/h) |
|-----|------------------|
| seg19 | 76.6 |
| **seg20** | **94.5**（峰值） |
| seg21 | 89.2 |
| seg22 | 85.6 |
| seg23 | 81.2 |
| seg24 | 78.0 |
| seg25 | 77.5 |
| seg26 | 75.7 |
| seg27 | 62.2（已降速） |

轮速报文证据（seg21）：`ESP_03.ESP_VL_Radgeschw` 实测 **84.3 km/h**（非 24），
`ACC_04.ACC_Geschw_Zielfahrzeug`＝99.2 km/h，`ACC_02.ACC_Gesetzte_Zeitluecke`＝4.0，`ACC_Abstandsindex`=215~217。

## 二、高速段确认存在真实雷达对象
seg21 的 radarState：**52/1200 帧 `radar=True, radarTrackId=26`**（dRel=71→83m，vRel=5.0~5.6m/s，modelProb 0.93~0.99）。
其余 1148 帧 `radar=False, radarTrackId=-1`（纯视觉回退）。
→ 高速跟车时**确有真实雷达轨道注入**（`_update_macan` 合成点），并非纯视觉。

## 三、旧标定表系统性偏低（用户的怀疑成立）
用 382 个雷达匹配点（seg19-23）对比距离误差：

| 方法 | 平均误差 | 中位 | 最大 | 系统性偏差 |
|------|---------|------|------|-----------|
| **旧表** interp(idx)→t→d=t·v | **17.2%** | 16.8% | 43.5% | **-17.2%**（低估） |
| **新线性** t=0.008718·idx+1.0178 | **1.4%** | 0.7% | 20.7% | **0.0%** |

旧表把前车距离系统性低估约 **17%**（例：idx=342 实测 t=4.016s→85.6m，旧表 t=3.221→68.7m，低估 17m），
这正是 Macan 用原厂 ACC 高速跟车时 op 误判距离过近、提前刹车/介入的根因。

## 四、推荐新标定（本次实测范围 idx 27~560 内）
**直接用线性公式替代查表（更简洁、避免高 idx 外推过冲）：**
```
t = 0.008718 * Abstandsindex + 1.0178    # 秒
d_rel = t * max(v_ego, 5.0)              # 米（v_ego 单位 m/s）
v_rel = (ACC_04.Geschw_Zielfahrzeug/3.6) - v_ego
```
实测范围 idx∈[263,420] 误差 <2%；idx 100~560 线性拟合均适用。
**高 idx（>560）旧表封顶 6.0s**，本次无实测点，保留原封顶值避免外推失真；
低 idx（<100）本次仅 1 点（idx135→t_est 2.195）单调线可覆盖，建议线性下插到锚点 t≈0.8s(idx→27)。

## 五、验证确定性公式（独立交叉）
- 时距法：`d = ACC_Gesetzte_Zeitluecke(4.0) × vEgo/3.6` → seg21 平均 **85.6m**
- 雷达真值：radar dRel 平均 **87.0m**（71~120m）
- 新表法：d_tab 平均 **85.0m**
三法互相印证（偏差<3%），确认公式 `d = t(idx)·vEgo` 物理正确，坏的是旧表的 t 值。

## 参考
- 表与拟合脚本：`opendbc_repo/opendbc/car/volkswagen/radar_interface.py`（_macan_abstands_t/idx）
- 复核工具：`/tmp/refit_full.py`、`/tmp/eval_table.py`（本次）
- 旧视觉标定：`ai/tools/recalibrate_abstandsindex.py`
