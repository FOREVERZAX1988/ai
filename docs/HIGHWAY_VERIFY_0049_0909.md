# 高速段验证：0004 确有高速，0049 纯低速（2026-09-09 复测确认）

## 结论速览
- **00000004（915ebf086f）**：确有高速跟车段，位于 **seg19~seg26（约 1200~1600s）**，
  峰值 vEgo **94.5 km/h**（seg20），随后 89→85→81→78→77→75 km/h 逐步减速。用户记忆成立。
- **00000049（ac8e2bc7b1）**：**无高速段**，全段纯低速市区，最高 vEgo 仅 **62.0 km/h**（seg32），
  其余绝大多数 <50 km/h。不宜用作高速纵向标定样本。
- 之前"0004 全段最高 24km/h"的结论是**扫描脚本 bug**（glob `--*--rlog.zst` 匹配不到 `--N/rlog.zst`，根本没读到数据），已修正。

## 复测方法（修正版）
- 正确 glob：`/data/media/0/realdata/{pre}--*/rlog.zst`（按 seg 数字序排序）
- 正确库入口：`sys.path.insert(0,"/data/openpilot")` + `from openpilot.tools.lib.logreader import LogReader`，
  且必须用 `/usr/local/venv/bin/python3`（system python3 无 cereal）
- 轮速 `ESP_VL_Radgeschw`：CAN ID **0x103**，信号 `16|12@1+` scale 0.1 km/h，
  **字节 = dat[2..3]**（低 12 位 LE），非 dat[0..1]（后者会误读成 ~299 常量）

## 0004 高速段实测（vEgo vs 轮速，单位 km/h，差 <0.6 物理一致）
| seg | vEgoMax | ESP_VL_RadgeschwMax |
|-----|---------|---------------------|
| 19  | 76.7    | 77.2 |
| 20  | **94.5**| **95.1** |
| 21  | 89.2    | 89.6 |
| 22  | 85.6    | 86.2 |
| 26  | 75.7    | 76.3 |

轮速与 vEgo 差 <0.6km/h，物理完全合理，ESP_VL_Radgeschw 解码正确。

## 0049 最高速 Top5
seg32=62.0, seg28=56.1, seg31=54.8, seg26=50.3, seg10=48.3 —— 均 <70km/h，无高速。

## 后续建议
- 高速纵向标定样本应取 **0004 seg20（峰值 94.5）** 或新采集 >80km/h 路段。
- 0049 仅适合低速/市区跟车拟合，不用于高速。
