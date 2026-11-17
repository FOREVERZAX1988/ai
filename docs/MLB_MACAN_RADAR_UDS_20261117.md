# Macan 雷达点云/UDS 探测归档（2026-11-17）

## 结论先行
这台 Macan（MLB 平台）的**原厂 ACC 雷达目标表不通过 panda 可见的 CAN 暴露，
也不通过 UDS 默认会话暴露**。软件层拿不到 raw target / 点云。
要真点云只能硬件搭接雷达私有 CAN，或破解扩展会话的私有 DID（未做，有风险）。

## 一、CAN 层证据
- 实时全量抓包（点火、P 档、20s，所有 src）确认：
  - src=2（原厂雷达域）只有 7 个 ID：`0x10D` ACC_05(50Hz)、`0x117` ACC_10(50Hz)、
    `0x127`/`0x395`/`0x6B9` 未定义（全恒定或仅计数器）、`0x30C` ACC_02(25Hz)、`0x324` ACC_04(25Hz)。
  - 每个帧最多 2 个字节在变（16 值计数器），**无任何多目标字段结构**。
  - DLC 全部 ≤8，**无 CAN FD 长帧**；panda 只接 3 路（src 0/1/2）。
- `opendbc/.../vw_mlb.dbc` 145 个 BO_ 无 raw target/cluster/角度/RCS 报文。
  `vw_mlb` dbc_dict 只有 `{Bus.pt:'vw_mlb'}`，无 `Bus.radar`（MEB 才有）。
- `radar_interface.py:42-44` 明确注释：Macan 原厂 ACC 模块内部消化目标表，
  只用 ACC_02.Abstandsindex + ACC_04 前车速度合成**单个** RadarPoint(trackId=1)。
- 10/18 高速跟车 route（vMax 13m/s，ACC_02 有效指数占比高）：`radarTracks` 有点时
  永远只有 1 点（某段 861/1200 条为 1 点）。

## 二、UDS 层证据（本次新增）
诊断仪插 OBD 做"读数据流"时实时抓包，工具链用 panda + `opendbc/car/isotp.py` 现成。

### 诊断寻址（重要教训）
VAG 雷达诊断**不在 0x7E0/29-bit**，而在 11-bit 物理寻址：
- **请求 `0x757`（src=0，动力 CAN）→ 响应 `0x7C1`（src=2/128）**
- 最初只过滤 `0x7DF/0x7E0-7EF/0x18DA` 全漏掉，靠全量扫 7xx 段才发现。
- 另有两个普通 ECU：`0x7E0/0x7E8`（ECM，VIN WP1AA2953FLB23826，EV_EC M20TFS02095B9062）、
  `0x7E1/0x7E9`（TCM，EV_TCMDLC50...）。两者 `10 03` 扩展会话成功，`22 F19E/F1A2` 正常。

### 雷达 ECU 0x757 的 DID 清单（90s / 7306 帧全量）
循环读的 4 个（各约 880 次，全是标量）：
| DID | 值 | 推测 |
|---|---|---|
| `0xF102` | `004289` | 电压/标定标量 |
| `0xF104` | `47`/`48` | 温度/计数标量 |
| `0xF106` | `000d` | 运行时间/计数 |
| `0x2555` | `8272` | 固定标量 |

开机各读一次的 11 个（身份标识）：`F190`(VIN)、`F187`、`F182`=108、`F189`=0800、
`F1A2`、`F1A3`=012、`F1DF`=40、`F18C`、`F197`、`F191`、`F1AB`。
只读服务 `0x22`，**无 `0x10` 会话切换、无 `0x27` 安全访问、无 `0x19` DTC**。

**结论：诊断仪"数据流"里的电压/角度/距离/运行时间就是这几个标量 DID，
不是 object list；雷达默认会话不暴露目标数据。**

## 三、风险分级（UDS）
- 🟢 `0x22` 读 DID / `0x19` 读 DTC：只读，基本无害
- 🟡 `0x10` 会话切换 / `0x3E` 保活：可能让 ACC_02 停发、雷达 ~9.25s 自报故障（fusion relay）
- 🟡 `0x27` 安全访问：错误尝试可能触发 ECU 锁定/惩罚延时
- 🔴 `0x11` 复位 / `0x2E` 写 / `0x31` 例程 / `0x34-37` 刷写：可触发 DTC、锁 ECU、变砖

## 四、后续可选路径
1. 受控扩展会话探测：仅 `0x10 03` + 读 DID 列表（不写、不解锁），风险相对可控 —— 本次执行。
2. 硬件搭接雷达私有 CAN：需查雷达模块型号/位置，加第二个 CAN 通道，并联取信号
   （不能断 relay，否则雷达 9.25s 自报故障）。
3. 诊断仪"编码/Coding"：写操作，**禁止点**。

## 五、工具脚本（均在设备 /tmp，未入仓）
- `uds_capture.py` — 诊断帧抓取（可过滤）
- `uds_fullhunt.py` — 全量 CAN 扫描（找隐藏诊断 ID）
- `radar_uds_stream.py` — 雷达 DID 数据流抓取
- `radar_probe_safe.py` — 受控扩展会话探测（停 comma 独占 panda，try/finally 恢复 safety）
- 日志：`/tmp/uds_capture.log`、`/tmp/radar_uds_stream.log`

## 六、扩展会话探测结果（2026-11-17 15:24，失败）
停 comma → 独占 panda → SAFETY_ALLOUTPUT(1) → 发 `0x10 03` + 扫 43 个候选 DID：
**全部 NO RESPONSE，连 sanity `22 F106` 都无应答**。finally 正常恢复 safety=25。

根因（已验证）：**诊断仪拔掉后，7xx 诊断段完全静默**（6 秒零报文）。
`0x757↔0x7C1` 这条 UDS 通道是**诊断仪插在 OBD 口时由网关动态建立的路由**；
诊断仪一拔，网关关闭该路由，panda 从网关侧发请求无人应答。
→ 结论：panda 网关侧**无法脱离诊断仪主动做雷达 UDS**；要做必须诊断仪保持插入并已握手。

### ⚠️ 事故记录（同一次尝试）
探测时曾**在 pandad 运行期间**用另一 Python 进程 `Panda()` 连接并改 safety(25→0→25)，
抢开 USB 句柄 → pandad 失去 CAN → `CAN Bus Disconnected`、ACC_05 停发、车报"ACC 需要服务"。
用户重新点火恢复。**铁律：pandad 运行时禁止并发连接 panda 或改 safety；
主动发帧必须先停 comma，且 try/finally 恢复 safety=25，结束重启 comma。**
最终验证：comma active、CAN 55964 帧/4s、ACC_05 st={2}、报警 NONE、safety=25、faults=0。
