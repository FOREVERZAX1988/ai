# Macan 融合距离 / SnG 误起步 —— 待办清单（2026-10-07，本会话取证后登记，暂不实施）

> 取证数据：route `00000091`(seg9, T≈668–690) / `00000002` / `00000004` / `0000007a` / `0000007b`
> 工具：`ai/tools/tmp_sng_trace.py`、`tmp_trace2.py`、`tmp_fit_lowspeed.py`、`tmp_idx_corr.py`（均为本会话自建）
> **状态（2026-10-09 更新）**：§1 为原登记待办 —— T4①/④ 已落地（见 §3），T4②/③、`aTarget`/`slopePct` 复活、
> SnG 次数限制**已改为 parked**（见 §4）。

## 0. 已实锤的事实（供后续任务引用）
1. `ACC_Abstandsindex` 是**时距索引** `t=0.008969*idx+0.332`；**vEgo≈0 时冻结不再更新**。
   实测冻结时长：7a 23.0s(idx=251)/24.7s；91 34.3s(idx=77)；02 33.3s(116)/65.6s(126)；04 49.7s(181)。
   车一动（v>0.5~1.2 m/s）**0.1–0.6 s 内恢复更新**（7a: 251→265）。
2. 冻结值 ≠ 静止时的真实车距，且**不是 idx 的静态函数**：静止样本 (idx↔视觉 x0)
   77↔3.5 / 116↔3.0 / 126↔3.25 / 181↔4.6 / 188↔6.1 / 251↔4.4（251 与 188 非单调）
   → 静止域**任何** idx→距离静态标定都不可能准。
3. 融合把冻结 idx 变成"恒定距离"：`A3(radar_interface)` 与 `A2(_macan_idx_to_drel)` 都用
   `d = t(idx) * max(v_ego, 5.0)` → 静止时 d = t(idx)*5 = 常数（07a 的 pin 点：5.11 m、10.09 m）。
   叠加 `A2 rel>0.3 → w=1`（原厂权重 100%）把**当时唯一准确的视觉距离整段丢掉**。
   **2026-10-09 更新**：`A2 rel>0.3 → w=1`（原厂主导）已删除（openpilot `af48eb247a`）。现语义 = 视觉主导、
   雷达只能改近；`d=t(idx)*max(v,5)` 仍是 A2/A3 的换算口径，但只有**比视觉更近**且过 `max(25%·d_vis, 2.0 m)`
   门时才被采纳 → 「更远」的钉子（10.09 m）不再生效。
4. `00000091` T=673.540 **OP 代发 LS_01 RESUME**（bus2, src=130, 80 ms 单脉冲）→ 12 ms 后原厂
   `loes=1 / anh 1→0 / Mom=63` 放行起步 → 车以 0.85 m/s 前挪 2.4 m（视觉 6.09→3.69 m），
   **dRel 全程钉在 10.09–10.11 m**（672.5→683.5，11 s）。触发链：
   `planner aTarget 0.108→0.152（跨 0.15 阈值）→ SnG 5 帧确认 → RESUME`。
   同一停车周期共 3 个脉冲：T≈673.5(生效)、679.0(原厂 anh=1 未响应)、682.5(未响应)；
   **T=683.5 原厂 ACC st=6（reversibler Fehler）→ st=2，OP 纵向退出(en 1→0)**，随后 T=684 车自行
   怠速前挪（v 0.37→0.67，st=2/en=0），驾驶员刹车接管。
5. `ACC_02` 帧率：bus2(src2)=1500 帧/60 s(25 Hz) vs **OP 自身输出 src=128（TX bus0）=1000 帧/60 s(16.7 Hz)**
   ——根因 `values.py:147 ACC_HUD_STEP=6`（注释即写 "ACC_02 message frequency 16Hz"）。
   route 91 另有 3426 帧（占比~9%）出现 `bus2 idx>0 而 bus128=0`（OP 拷贝丢值）；
   12530 帧 `bus2=0 而 bus128>0`（OP 视觉补值，符合设计）。
6. `0924 版算法 = 现值`：`git show origin/macan-long-0924:.../radard.py` 的 B1 系数、`max(v,5)`、
   A2 的 `rel/w/w_vis/dist_factor`、平滑(0.5)+限幅(1.0 m)+滞回(0.6 s) **全部与当前 HEAD 相同**
   → 这不是回归，是 0910 方案B 起就存在的设计缺陷；**2026-10-09** 该「原厂主导」方案已整体删除（`af48eb247a`），
   本条仅作历史取证。

## 1. 待办（按优先级）

### T1【最高】低速/静止域：idx 判无效、回退视觉（融合权重修正）
> **状态（2026-10-09）**：主症已解 —— 冻结 idx 只有**比视觉更近**且过 `max(25%·d_vis, 2.0 m)` 时才被采纳
> （`af48eb247a`），seg9 的 10.09 m 钉子不再生效；`rel>0.3→w=1` 已删除。
> **残留**：融合层**没有**冻结豁免（只有 SnG 门有），冻结值若比视觉*更近*仍会进 dRel → 见 §4 P4。
- 触发条件（对称方案 A 与 B 均可复用）：`vEgo < 2 m/s` 且 `idx 在最近 0.5 s 内未变化` → 视 idx 失效。
  依据：所有 ≥1 s 的冻结窗口 maxV ≤ 2.19 m/s；>7 m/s 的 1–2 s 冻结属"正常抖动"。
- A2 的 `rel>0.3 → w=1` 必须在这条规则命中时禁用（否则视觉权重恒 0）。
- 备选（仅兜底，不要单独用）：把 `max(v,5)` 的 5 m/s 换成 ~2.5–3.5 m/s（实测冻结速度
  v_f=2.19–3.42 m/s）；用户提的 `d=idx/30` 数学上 = `t(idx)*3.72`，等效于把 floor 降到 3.7 m/s，
  比 5 m/s 更接近真值（5 个静止样本误差 ≤1.4 m vs 现值 1.6–5.2 m），但仍是统计凑合，
  逐例误差 ±40% → 不作为主方案。

### T2【高】方案 A vs B 的最终取舍（本会话结论：取 B 骨架 + A 兜底，不做二选一）
- 保留融合的**移动域**（v>3 m/s）A2（实测 RMS 0.67 s 可用，corr(idx,t)=0.89）。
- 低速/静止域按 T1 直接回退视觉（= A 的精神），而不是 `t*max(v,5)`。
- B①（关键域取 min）仅在雷达值为**新鲜有效**时参与；冻结值不参与 min（否则 min 天天生效，
  且掩盖问题而非解决）。B② 不管 A/B 都必须加（见 T4）。
- 若 A2 要做"视觉/雷达一致性取舍"，需先解决"视觉本身浮动"（现有平滑 0.5 s + 限幅已部分覆盖）。

### T3【中】idx→距离 低速段重新标定（结果已出，待决定是否改表）
- 分速度带回归（radar=0 视觉 lead，`t=dRel/v`，|vRel|≤0.3）：
  | v 带(m/s) | n | t = a*idx+b | RMS | 实测 t 中位 / 现表 t 中位 |
  |---|---|---|---|---|
  | 0.5–2 | 5903 | 0.0277·idx+0.385 | 3.39 s | 4.94 / 1.80 → **2.36×（该带不可用）** |
  | 2–4 | 7985 | 0.01165·idx+0.306 | 0.64 s | 2.33 / 1.91 → 1.19× |
  | 4–8 | 19093 | 0.00829·idx+0.282 | 0.66 s | 1.76 / 2.00 → 0.89× |
  | 8–15 | 31151 | 0.00783·idx+0.290 | 0.53 s | 1.93 / 2.28 → 0.86× |
  | 15–30 | 8472 | 0.00809·idx+0.198 | 0.22 s | 2.03 / 2.35 → 0.86× |
- **按 Zeitluecke 分层（新发现，重要）**：zl=4 → `t=0.00790·idx+0.280`（中位 1.83 s，n=48945）；
  zl=3 → `t=0.00848·idx+0.584`（中位 2.34 s，n=3180）。**现 B1 表(0.008969/+0.332)更接近 zl=3 人群**，
  而本车常跑 zl=4 → 移动域也会系统性偏远 ~10–14%（与用户"融合距离偏远"体感一致）。
  ⚠️ 截距受 `RADAR_TO_CAMERA=1.52 m` 参考系与 v_vis/v_can 配准影响，斜率结论比截距可靠；
  改表前需做一次"同目标配对实验"（同一帧 vision x0 与 idx 同步落盘）确认。
- `idx` 相关性：corr(idx, dRel)=0.83、corr(idx, t=d/v)=0.89、corr(idx,√)=0.89、corr(idx,log)=0.86
  → 线性仿射已足够，不需要更复杂映射；idx 与 vEgo 相关仅 0.23（说明 idx 不是速度信号）。

### T4【高】SnG 起步管控（本次 st=6 的直接闸门）
> **状态（2026-10-09）**：①④ 已落地（`793f6ed420` + opendbc `2585bce68`，见 §3.1）；②③ parked（§4 P2/P3）。
- ✅①【已落地】增加辅助条件：**前车速度>0 持续 ≥1 s**（用 ACC_04 `ACC_Geschw_Zielfahrzeug` 与视觉 vLead
  双重确认；实测原厂该信号在静止时稳定为 0）+ **判定车距 > 6 m**。
  ⚠️ **实现注意**：`stop_and_go.py` 里 `vis_dist = CS.op_lead_dRel` 名为"视觉"，实际是
  `card.py` 注入的 **radarState 融合值**（= 被钉死的 10.09 m）→ 用它做门等于门失效。
  必须改用 modelV2 `leadsV3[0].x[0]` 原值（或 min(视觉, 新鲜雷达)）。
- ⏸②【Parked §4 P2】同一停车周期只允许 1 次 RESUME：脉冲发出后若车未动/已回到 standstill，则直到
  前车真正移动或驾驶员物理按键，才允许下一次（现只有 3 s 冷却 → 实测 673.5/679/682.5 三连发）。
- ⏸③【Parked §4 P3】"想多挪一点"时不要发 RESUME/SET，改为**跟随原厂自己的 loes=1**（原厂决定前挪时才跟），
  或干脆不主动请求（KB `MLB_MACAN_ACC_LOGIC.md` §13.2 A 层 loes 跟随思路）。
  OP 当前无"松 EPB/ESP 保持让车怠速滑行"的独立通道，需先确认可行性再议。
- ✅④【部分落地】起步距离门与 A2 共用同一份"新鲜度"判定，禁止冻结 idx 参与（`radar_ok = idx*0.0424>5`
  在 idx=188 冻结时给出 7.97 m，是本次误起步能通过门的原因之一）。

### T5【中】bus128(OP TX) 的 ACC_02 丰富度
- 提高 OP 自身 ACC_02 发送率到 ≥25 Hz（`ACC_HUD_STEP` 6→4，MQB 就是 4）；
- `stock_lead_distance>0` 时必须**逐帧透传**原厂值，不做 `disp_abstand` 限幅，消除 9% 丢值帧。

### T6【低】复现与回归
- 本次事故 route（00000091 seg9）可作 SnG 回归用例；补一条"原厂 idx 冻结 + 前车静止 30 s"的
  仿真用例，断言：fused dRel 必须跟随视觉、SnG 不得发 RESUME、不得出现第二个脉冲。

## 2. 待用户确认的问题（本会话遗留）—— 2026-10-09 已定
- `MacanStartStopDistance`：已取消 Off，范围 3~10 m、**默认 6 m**（`793f6ed420`/`2585bce68`）；
  闸门2 实际门 = `max(3 m, 设定值)`。
- 「冻结即失效」判据：**采纳** `vEgo<2 m/s` 为唯一额外条件（`_IDX_STALE_VEGO=2.0` + 静默 50 帧 @100 Hz）。
- zl=3/4 的表差异是否要按档位分表（B4 双表）还是统一用 zl=4 表 + 保守余量？


---

## 3. 本轮实施（2026-10-07 晚，已完成并推送）

### 3.1 SnG 起步闸门（原方案①，代码已落地）
`opendbc/sunnypilot/car/volkswagen/stop_and_go.py` 新增双闸门，`update_stop_and_go()` 顺序：
`enabled → 驾驶员干预 → 脉冲锁定 → 冷却 → standstill → 挡位 → 原厂 st==3 → **闸门1** → **闸门2** → aTarget`。

* **闸门1（前车必须在动）**：原厂 `ACC_04 ACC_Geschw_Zielfahrzeug`（经 `ACC_02 Relevantes_Objekt==1`
  确认有跟踪目标）优先；原厂无目标时用视觉 `vLead` 补位。>1 km/h 且**连续 ≥1 s**（100 帧 @100 Hz）
  才放行。前车静止（红灯跟停/seg9 事故场景）一律不代发。
* **闸门2（判定车距）**：`d_used > max(3 m, MacanStartStopDistance)`，其中
  `d_used = min(视觉, 新鲜 idx×0.0424)`——两侧都有值时 min>门 ⟺ 两侧都过门（= 用户要求的
  「视觉和 idx 都要过门」）；只有一侧有目标时由该侧兜底（静止车队原厂雷达无目标 → 视觉；
  视觉漏检 → 雷达）。
* **idx 冻结豁免**：低速域（`vEgo < 2 m/s`）内 idx 静默 ≥0.5 s（50 帧）→ 判冻结，不得参与距离门
  （实测冻结只发生在 ≤2.19 m/s）。**这就是 seg9 那次误起步的根因拦截点**（idx 冻结 188 = 7.97 m）。
* **视觉源必须是 modelV2 原始前车**，不能用 `CS.op_lead_dRel`（radard 融合值，被冻结 idx 钉在
  10.09 m）。链路：`controlsd_ext` 取 `modelV2.leadsV3[0]`（`x[0]−1.52`、`v[0]`、`prob≥0.5`）
  → `CC_SP.params[visLeadDist/visLeadVLead]` → `carcontroller.set_vision_lead()` → 闸门。
* 原方案 **②「同一停车周期只允许 1 次 RESUME」不做**（用户决定：前车临近绿灯先挪一下又停再起步
  时会让 SnG 失效）。
* 原方案 **③「停车过远改蠕行/loes 跟随」仍未做**（需实车确认 `Anhalten=1` 时能否纯 accel 蠕行）。

### 3.2 ⚠️ 新发现（本轮实测）：`CC_SP.params` 通道一直失效
* `pycapnp 2.1.0` 的 `_DynamicListBuilder` **没有 `append()`**（只有 `adopt/disown/init`），
  历史 `CC_SP.params.append()` 抛 `AttributeError` 被 `except: pass` 吞掉。
* **证据**：route `00000049`（2026-10-07 08:07，本机）逐帧读 `carControlSP.params` → **恒为 `[]`**
  （1201 帧）；`custom.CarControlSP` 现场探针 `params.append()` → `AttributeError`。
* 后果：**`aTarget` / `slopePct` 从未送达 carcontroller** → SnG 一直在用 `CC.actuators.accel`
  而不是 planner `aTarget` 判定；`self.slope_pct` 一直是 0（纯OP 坡度补偿用它、融合模式拿它做
  IMU 复核）。**因此 seg9 那次 RESUME 的真实触发源是 `CC.actuators.accel > 0.15`，不是 aTarget。**
* 本轮的 `visLeadDist/visLeadVLead` 已改用**整表赋值**（`CC_SP.params = [ {...}, {...} ]`）绕开该缺陷，
  并有用例覆盖生产→capnp→消费全链路（`ai/tools/test_macan_sng_params.py`，8/0）。
* 复活 `aTarget`/`slopePct` 会改变①SnG 触发源 ②坡度补偿，属需单独路试验证的行为变更 →
  **未夹带本轮**，见待办。

### 3.3 验证结果
* `ai/tools/sim_test_macan_sng.py`：**60 通过 / 0 失败**（原 51 项 + 新增场景组 2h 共 9 项闸门回归：
  seg9 前车静止 0 次代发、前车在动 <1 s 不代发 / ≥1 s 代发、视觉 3.69 m 被门拦、idx 冻结被排除、
  雷达兜底、无目标 0 次代发）。
* `python3 -m unittest opendbc.car.volkswagen.tests.test_macan_mlb`：**37 OK**。
* `ai/tools/test_macan_sng_params.py`：**8 通过 / 0 失败**。

### 3.4 尚未做（下一步）
* ~~融合侧 closer-only~~ **已完成并推送**（openpilot `af48eb247a` / opendbc `2585bce68`）。
* **idx→米 仍未同源（4 处）**：B1 表在 `radard.py` / `radar_interface.py` / `carcontroller.py` 各存一份（同系数、
  靠注释约束），而 SnG 门用的是另一套 `stop_and_go._IDX_TO_M = 0.0424`（忽略 +0.332 截距）——idx=188 时
  B1 给 10.09 m、SnG 给 7.97 m，差 2.1 m。**本轮 seg9「看起来有效」正来源于此**（§4 P4）。
* 闸门③（停车过远蠕行）与 SnG 门阀的实车验证（下一次 offroad 路试）。

## 4. Parked（2026-10-09 用户明确「先放着 / 暂不做」，路试后再议）

### P1 `aTarget` / `slopePct` 复活（`CC_SP.params` 通道）
- 通道缺陷已用**整表赋值**绕开（`visLeadDist/visLeadVLead` 走这条路径），但 `aTarget`/`slopePct` 仍未复活：
  SnG 触发源仍是 `CC.actuators.accel`，纯 OP 坡度补偿仍是 0（融合模式「IMU 复核」分支实际没工作）。
- 用户决定：写进待办放着，**目前看不出毛病，暂不动**；复活 = 同时改 ①SnG 触发源 ②坡度补偿 → 单独一轮 + 路试。

### P2 SnG RESUME 次数 / 同一停车周期限制
- 用户决定：**不做**。理由：前车临近绿灯先挪一下又停再起步时会让 SnG 失效；走走停停也无法用固定次数(3)覆盖；
  前置门阀（闸门1 + 闸门2 + 冻结豁免）到位后认为无必要。
- 证据仍留 §0.4（seg9 三连发 673.5 / 679.0 / 682.5）；路试若再现连发，从本条重启。

### P3 停车过远 → 蠕行 / 跟随原厂 `loes`
- 需先实车确认 `Anhalten=1` 时能否纯 accel 蠕行（OP 现无独立通道），未做。

### P4 idx→米「多源同源」+ 文档同步（2026-10-09 新记录）
- 换算共 4 处：B1 表 ×3（radard / radar_interface / carcontroller，同系数不同文件）+ SnG 门 `0.0424`（不同公式）。
  建议收敛为单一函数（B1 表 + `max(v_ego, 5.0)`），SnG 门直接调用。
- 融合层目前**没有**冻结豁免（只有 SnG 门有）：冻结值若比视觉更近（|Δ| ≤ max(25%·d_vis, 2.0 m)）仍会被采纳
  → 若要「完全视觉主导 + 雷达只可改近」，这是唯一残留缺口。
- 文档待同步（仍按旧语义「原厂主导 / A1 速度加权 / MACAN_A2_REL_TH」描述融合）：
  `MLB_MACAN_PLANB_FIT_0910.md`、`MLB_MACAN_PURE_OP_0915.md`、`MLB_MACAN_DISPLAY_SOURCE_2A_1004.md`、
  `MLB_MACAN_SNG_AB_PLAN_1006.md`、`MLB_MACAN_FORMULA_CROSSCHECK_0910.md`、`MLB_MACAN_TODO_NEXT.md`
