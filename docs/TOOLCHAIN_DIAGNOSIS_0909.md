# 工具链紊乱诊断与修复 —— 全文记录（2026-09-09，已执行修复）

## 症状
- 部分工具不可用/行为异常（`search_tools`/`load_tool` not implemented、`list_drive_routes` 只显示最新、
  `read_params`/`read_file`/`get_vehicle_state` 等工具描述被注入历史失败"Evolved hint"）
- 预期该有的 CAN 扫描/拟合工具"时有时无"（实际脚本都在，问题在工具描述注册表被污染）

## 根因（三层）
1. **代码子模块 vs 运行时目录分离**
   - `/data/openpilot/ai` = git 子模块（origin=`FOREVERZAX1988/ai.git`，分支 macan-long-0907，HEAD=09c1694），
     工具脚本（`tools/fit_abstands_canonly*.py`、`scan_*.py` 等 47 个 untracked）都在此。
   - `/data/ai` = 运行时状态目录（`config.json`、`config.large.*` 等），非 git。两目录真实分离，非软链。
2. **本地分支 vs 上游 main 分叉**
   - 上游 `mouxangithub:main`（合并 b8f5d87→846af46 等 cabana UI/replay 新功能）领先本地；
     本地 `macan-long-0907` 落后 5+ 提交且带大量未提交工具脚本。
   - **关键结论：本地工具脚本全在本地分支上（uncommitted/或已提交于本地分支），上游 main 合并不会丢失它们，
     但会引入新功能；真正紊乱源不是目录合并，而是 config 工具描述污染（见下）。**
3. **config.json 工具描述污染（本次实质根因）**
   - `/data/ai/config.json` → `ai_tool_desc_overrides`（JSON string，48 keys）中累积了 13 个 `call_*` 历史会话
     失败"Evolved hint"条目 + 24 个 `__meta_call_*` 元数据（共 26 个污染键），被当作工具描述注入，污染工具解释。
   - `ai_evolution_tool_desc` = "1"（仅开关标志，非污染源）。

## 已执行修复（本会话）
- **备份**：`/data/ai/config.json` → `config.json.bak-toolchain-<ts>`
- **清除污染**：删除 `ai_tool_desc_overrides` 内全部 `call_*` + `__meta_call_*`（26 键），
  保留 11 个合法工具名描述（run_shell/get_vehicle_state/read_file/run_shell_command/read_params/
  panda_firmware_status/read_onroad_events/ssh_readonly_exec/extract_can_ids_from_route/
  route_event_timeline/analyze_route_summary）。现剩 22 键。
- **验证 CAN 扫描/拟合工具链可用**：`/usr/local/venv/bin/python3` + LogReader 可正常解析 CAN；
  `ai/tools/fit_abstands_canonly_v2.py 00000002 10,11` 能拟合出 idx→时距表（v2 里程积分法全帧约束）。

## 关键信号定义（DBC 确认 vw_mlb.dbc）
- BO_ 780 (0x30C) ACC_02: `ACC_Abstandsindex` 24|10@1+ (1,0) [1|1021] —— **时距(time gap)** 连续信号
- BO_ 804 (0x324) ACC_04: `ACC_Geschw_Zielfahrzeug` 40|10@1+ (0.32,0) [0.00|326.72] **Unit_KiloMeterPerHour**
  ⚠️ **单位为 km/h**（用户明确纠正，勿记成 m/s）。比例因子 0.32，读值 320+ → 哨兵（脚本 vlead>=320 判 None）
- `ACC_Wunschgeschw_02` (BO_780) 12|10 (0.32,0) km/h

## 全路线高速路段扫描结论（重要）
对全部 route 族采样扫描 vEgo 峰值（每 N 段抽 1，每段封顶 2~4 万条消息）：
- **00000004**（915ebf086f，59seg）：vmax 最高仅 ~24 km/h（seg15）。**用户记忆的"1222~1600s 高速段不存在"**，
  该窗口（seg~20-33）实测 vmax 9.9~21 km/h，均为低速跟车。
- **00000049**（ac8e2bc7b1，39seg）：vmax 最高 ~17 km/h，完全低速市区。
- **00000002 / 00000003 / 00000071 / 00000072**: vmax 最高 ~16 / 8.8 / 13.2 / 16.3 km/h，均无高速。
- **结论：现有全部 routes 均无 >80 km/h 高速路段，无法用现有数据做高速标定样本；高速标定需新采集。**
