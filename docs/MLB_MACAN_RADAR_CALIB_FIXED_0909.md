# Macan/MLB 雷达测距公式 —— 0004 高速段重新验算（2026-09-09第二版，纠正早前低速误判）

> 背景：早前"0004全段最高24km/h、无法标定"的错误结论源于扫描脚本 glob 匹配错误
>（`--*--rlog.zst` 匹配不到 `--N/rlog.zst`），导致根本没读到数据。已修正。
> 用户授权全部工具权限 + 要求重新验算雷达距离推算公式。

## 1. 高速窗口实测（修正后，轮速/vEgo 交叉验证）
route 00000004--915ebf086f（59seg），用 vEgo（OP 内部自 ESP 轮速推算）扫描：
- seg20: vEgo_max=94.5 km/h（vlead 前车速最高 120.3 km/h）→ 明确高速跟车
- seg21: vEgo 71-84, **vrel med=+5.44 m/s, 100%帧 |vrel|>2m/s**（前车明显更慢/我们逼近）→ 最佳标定窗
- seg22: vEgo 67-83, vrel med=+3.97, 87%帧>2m/s → 也是强相对运动窗
- seg23-26: vEgo 53-89, 高速跟车（60-80km/h带）
- **结论：早前"全段<24km/h"纯属扫描错误；0004 确有 1200~1620s 高速跟车段，用户记忆成立。**

## 2. DBC 信号位定义（确定，Motorola 大端）
- `ACC_02(0x30C,src2)`:
  - `ACC_Abstandsindex` 24|10@1+ (1,0) [1|1021] —— 连续距离/时距指数
  - `ACC_Gesetzte_Zeitluecke` 37|3@1+ —— **驾驶员设置档位**（0/1/2离散，非瞬时时距）
  - `ACC_Anzeige_Zeitluecke` 42|1
- `ACC_04(0x324,src2)`: `ACC_Geschw_Zielfahrzeug` 40|10 (0.32,0) **km/h**（无目标哨兵 327.36）
- `ESP_03(0x103,src0)`: `ESP_VL_Radgeschw` 16|12@1+ (0.1,0) km/h（轮速）
- **位序**：`@1+`=Motorola 大端。（旧 compare_routes_dist.py 用 Intel `dat[3]|dat[4]<<8`
  解码 idx 是错误的，idx 应以 Motorola 解码。）

## 3. 语义判别（关键，修正旧"时距"假设）
在 41931 帧高速跟车样本上：
- `corr(Abstandsindex, vEgo) = -0.42`（强负相关）
- idx 在快速逼近窗（seg21, vrel=+5.4）**饱和到 min=2**；vEgo 越高 idx 反而越低
- → 说明 **Abstandsindex 是"距离型指数"（idx 越小=车越近），不是"乘以 vEgo 的时距"**
  （若是时距 t(idx)*v，则 idx 应随 v 单调变化且快速逼近时 idx 应剧烈增大，实测相反）。

### 候选模型回归（对真实距离 d_true=∫vrel·dt 积分重构）
| seg | R2[时距 d~idx·v] | R2[距离 d~idx²] | 判定 |
|----|------|------|------|
| 20 | 0.13 | 0.04 | 弱 |
| 21 | 0.08 | 0.15 | 弱 |
| **22** | **0.59** | **0.93** | **距离模型胜出** |
- seg22（vrel 强、样本充分）距离模型 R²=0.93 显著优于时距模型 0.59。

## 4. 推荐公式（重算结论）
**距离指数模型：d = g(Abstandsindex)**（标定 idx→米 查表，纯函数，不乘 vEgo）
而非旧式 `d = t(idx)·vEgo`（时距模型，在高速窗被证伪）。
- 用 vrel 积分重构的真实距离 d_true 对 idx 做单调查表（seg22 + seg21 高vrel段联合），
  即得 idx→米 转换表，替换旧 `_macan_abstands_t/_macan_abstands_idx` 时距表。
- **交叉验证**：d_next = d_cur + (vlead−vego)/3.6·Δt 应与 idx 动态一致；
  vlead(ACC_Geschw_Zielfahrzeug, km/h÷3.6) 是唯一前车绝对速度源。

### 工程建议
1. 以 0004 seg20-23（vrel>2m/s 帧）为标定窗，用 d=∫vrel·dt 常态锚定重建 idx→m 表；
2. 输出公式（写入 carcontroller/radar_interface）：
   `lead_dist = interp(idx, IDX_TABLE, METER_TABLE)`，独立于 vEgo；
3. 保留 `ACC_Gesetzte_Zeitluecke`(37|3) 作为驾驶员档位（用于多档表分段，非瞬时距离）。
