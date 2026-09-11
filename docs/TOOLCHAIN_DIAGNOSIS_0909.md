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

---
## 追加：config 清理被 daemon 内存覆盖（2026-09-09 同会话）
- 现象：直接编辑 `/data/ai/config.json` 的 `ai_tool_desc_overrides` 清除 call_* 污染后，
  运行中的 `ai.aid` daemon（pid 33584，listen:5090，由 launch_chffrplus.sh watchdog 每 45s 守护）
  持有 config store 内存缓存，下一次 `put` 写盘时把内存里的旧污染重新写回 → 我的文件修改被回滚（48→26）。
- 机制：`ai/common/config_store.py` 单例内存缓存 + 节流异步写盘；`_load` 从 Params/config.json 读、
  `_save` 限制 `_MAX_OVERRIDES=48`。`ai_tool_desc_overrides` 未暴露 REST API。
- **修复需重启 daemon 生效**：`kill 33584`（或 `kill $(pgrep -f "ai\.aid")`），watchdog 45s 内自动重启，
  从已清理的 config.json 重新加载；内存旧缓存即失效。
- 备份：`/data/ai/config.json.bak-toolchain-20260909-045919`（清理前全量）。
- 根因分级：
  - **实质根因**：config.json 的 `ai_tool_desc_overrides` 累积 13 个 `call_*` 历史会话失败
    "Evolved hint" + 13 个 `__meta_call_*`（共 26）污染工具描述。清除后需重启 daemon 固化。
  - 上游 me.../main 合并仅是次要（引入 cabana 新功能），**不会丢本地工具**（47 个工具脚本已在本会话
    commit dd8b9dd 固化到 macan-long-0907）。

## 追加二：全局低速结论被证伪 —— 0004 确有高速段（2026-09-09 06:30）
- 上一版记录"0004全段最高~24km/h、无高速"是错误的，源于扫描脚本 glob 匹配错误（`--*--rlog.zst` 匹配不到 `--N/rlog.zst` 实际路径），导致根本没读到数据。
- 修正后（glob `--*/rlog.zst` + 按 seg 目录数字序）用轮速 `ESP_VL_Radgeschw`(ID259,0x103,16|12@1+ scale0.1 km/h) 实测 0004 全 59 段：
  - 高速段 **seg20~26（约 1200~1620s）**：seg20 vEgo 94.5/轮速95.1 最高 → seg21 89.2 → seg22 85.6 → seg23 81.2 → seg24-26 78/77.6/75.7。
  - 用户所说"1222~1600s 高速跟车段"成立（超80km/h集中1200-1440s）。
  - 轮速与 vEgo 差 <0.6km/h，物理一致，ESP_VL_Radgeschw 完全合理。
- **0049**（39seg）：纯低速市区，采样最高 vEgo 47.5km/h，无高速段。
- **工具根因（目录）修正**：正确导入 openpilot 库 = `sys.path.insert(0,"/data/openpilot/openpilot")` + `from tools.lib.logreader import LogReader`，须用 `/usr/local/venv/bin/python3`（system python3 无 cereal）。所有 scan/fit 脚本应统一此入口。

---

## 0909 补充：工具链根治复查（追加）

### 复查范围（用户要求彻底根治）
对 ai 子模块相对 upstream/main 的差异做了接线级审计。

### 结论
1. **核心接线文件零污染**：`core/tools/pipeline.py`、`core/agent/agent.py`、
   `tools/deferred_loading.py`、`tools/extensions.py`、`tools/agent_tools.py`、
   `server/handlers/chat_handlers.py` 相对 upstream/main 均无 import 层改动。
2. **新发现并修复污染点（toolsets.py）**：本地曾把 `TOOL_META` 的 import
   从函数内懒加载上移到模块顶层，破坏注释明确标注的
   `agent_tools → extensions → platform_extensions → toolsets → agent_tools`
   循环导入保护。已还原为上游懒加载（与 upstream/main 一致），
   导入与工具过滤功能实测正常。
3. **存量 param 已干净**：`ai_tool_desc_overrides` 无 `call_*` 伪键（commit 2d35d6f 生效），
   仅剩正常 `__meta_*` 元数据键。
4. **search_tools/load_tool 属设计如此**：它们的 schema 由 `apply_deferred_filter`
   （`ai_deferred_tools=True`）在会话时注入，不进 TOOL_META/基础 schema，属正常 deferred 设计。

### 为什么之前「运行着运行着又坏」
工具链在 ai.aid 服务侧当前健康；间歇性 `not implemented` 源于 RL 宿主网关的
工具注册表与 ai.aid 服务不完全一致，而非 ai.aid 仓库代码被执行破坏。
关键原则：工具链代码以 ai.aid 仓库（macan-long-0909）为唯一可信源，不因
宿主侧展示差异而反复改结论。

### 需要推送
- 还原后的 toolsets.py
- 3 个探针脚本（probe_0x127_0x395 / probe_0x127b / probe_0x127c，步骤B收尾用）

---

## 存档追加：search_tools/load_tool 反复 UNKNOWN_TOOL 的真正根因与根治（2026-09-11）

### 复现 + 实证（本会话）
- ai.aid 侧代码完全健康：直接调用 `handle_search_tools`/`handle_load_tool` 返回 ok:True。
- 但宿主/直查 handler 表执行时返回 `{'error': "Tool 'search_tools' not implemented", 'error_code': 'UNKNOWN_TOOL'}`
  —— 措辞与 `pipeline.execute` 第 216 行完全一致，证明调用进了 **handler 表查找**而非 Agent 的 `_execute_special_tool` 旁路。

### 真正根因（接线缺口，非代码损坏）
- `search_tools`/`load_tool` 的 **schema** 由 `deferred_loading.apply_deferred_filter` 在会话时强制注入 LLM 可见工具列表；
- 但它们的 **handler 从未注册进 `make_handlers()` 的 handler 表**（agent_tools.py，329 个 handler 不含这两个）。
- Agent(`_execute_special_tool`) 会较早拦截走旁路 → ai.aid 正常；但任何**不走 Agent、直查 handler 表**的执行层
  （pipeline / execute_tool_async / 宿主 RPC / 串行执行器）都会 `UNKNOWN_TOOL`。
- 这就是"反复修反复坏"的本质：schema 层永远可见、handler 层永远缺失 → 非对称 → 一换执行入口就复发。
  （此前误以为是"RL 宿主网关注册表不一致"，实为本仓库内的接线缺口；宿主只是暴露了它。）

### 根治（本会话已改）
- `ai/tools/agent_tools.py::make_handlers()` 在 `register_mcp_handlers` 之后、`return` 之前，
  为 `search_tools`/`load_tool` 注入兜底 handler，委托给 `deferred_loading.handle_search_tools/load_tool`，
  并用 `handlers.setdefault(...)` 保证不覆盖（Agent 旁路仍优先，兜底仅在查表路径触发）。
- 验证：make_handlers 返回 331 handler（含 meta 两个）；Agent catalog 初始化后 search/load 返回 ok:True；
  `ai.aid` 完整导入链路 smoke 通过。
- 需重启 ai.aid（kill 现有进程，watchdog 45s 自动拉起）让单例 handler 缓存重载。

### 备忘
- 用户终端里 `python -c "from ai.plugins import loader; loader.collect_plugins()"` 报 AttributeError：
  `loader` 无 `collect_plugins`（正确 API 是 `list_plugins`）。这是 MD/文档指引过时的又一例证，
  与工具路径文档未同步的情况同类。
