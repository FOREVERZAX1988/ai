# Macan 雷达测距 —— 高速标定精修 + 表格落地 (2026-09-09 第二轮)

> 背景：用户指出早前"route 0004 全段 ≤24km/h"结论荒谬（原厂 ACC 起步 ≥30km/h），
> 要求用轮速（ESP_VL_Radgeschw）复验并重新验算雷达距离推算公式。
> 本轮确认用户完全正确，并落地一版以真实高速 CAN 数据精修的 idx→时距表。

## 1. 复验结果：route 0004 是高速路（用户对，早前扫描错）
用 `ESP_VL_Radgeschw`（ESP_03 BO_259，16|12@1+ 0.1km/h，bytes2..3 低12位）全量扫 0004 全部 59 段：
- 高速段：seg19~27（76–95 km/h，>60km/h 帧数千）、seg5(73)、seg6/7(62–65)、seg35(64)、seg40(61)
- seg20 峰值 95.1、seg21 89.6、seg22 86.2、seg23 81.7 km/h —— 稳定高速跟车样本充足
- 轮速 vs carState.vEgo：wheelMax≈vEgoMax（+0.2–0.5 轮速略高，正常）
- **早前 24km/h 结论根因**：扫描脚本误从 bytes0–1 解轮速（那是另一信号），且数据源解析有误。
  正确字节 = `(dat[2] | (dat[3]<<8)) & 0xFFF`（LE 12bit @位16）。

## 2. 公式形态与表精修（训练 seg19–25，留出 seg26–27 验证）
**形态确认：`d_rel = t(ACC_Abstandsindex) · v_ego`（时距模型）**
- 对比：直接距离模型 `d=g(idx)` 在留出集爆炸（中位相对 21.7% vs 4.30%），时距模型正确。
- 速度无关性：同一 idx 带内 corr(t=d/v, vEgo)=−0.45~−0.62（弱负），时距模型整体成立；
  低速去量化分级是剩余误差主源，非公式系统错误。

**精修流程**：按 5-idx 分箱求中位时距 t=d_vis/vEgo → 单调累计 → 3点平滑，
在**旧表 idx 网格**上，用新 CAN 标定值替换 idx=62..430 带（高速有充足样本），
idx<62 保留旧近贴低表（0.81s），idx>430 稀疏尾保留旧表防外推过冲。

**留出集验证（seg26/27, n=9476）**：
| 表 | 中位相对 | 平均 | 中位绝对 |
|----|--------|------|--------|
| 旧表 | 4.63% | 7.39% | 1.28m |
| **精修 merged** | **4.29%** | **6.71%** | **1.14m** |
| 提升 | +0.33pp | +0.67pp | +0.15m |

## 3. 落地（已写入代码）
- `ai/tools/abstands_t_table.json` 与 `ai/tools/abstands_idx_table.json` 已更新（153 点，idx 网格不变）
- `opendbc_repo/opendbc/car/volkswagen/radar_interface.py` `_macan_abstands_t` 数组已替换（单行 diff）
- 运行时模块加载验证：153 值，idx72–82 新高速值生效

## 4. 结论速记（勿再回退）
- ✅ 0004 含大量 60–95km/h 高速跟车——早前"全低速/方案A不可行"**废弃**。
- ✅ 公式 `d = t(idx)·v_ego`，v_ego 用 ESP 四轮轮速均值÷3.6（m/s）。
- ✅ 时距表已用真实高速 CAN 精修并落地，留出集全面优于旧表（4.29% vs 4.63% 中位）。
- ⚠️ idx<62 近贴与 idx>430 超远尾仍用旧表锚定，待专用低/超远采样再补。

## 5. 参考脚本
- ai/tools/scan_0004_speed_full.py —— 轮速全量扫 0004（正确字节）
- /tmp/calib_finalA.py、/tmp/calib_models.py、/tmp/validate_merged.py —— 本轮精修/形态判别/留出验证
- ai/tools/fit_abstands_canonly_v1/v2/v3.py —— 旧纯lstsq（判为规范不可辨识，仅参考）
