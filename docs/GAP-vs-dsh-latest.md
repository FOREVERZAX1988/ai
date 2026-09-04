# GAP: E:\sp\ai vs E:\deepseek-harness 最新差距清单

- 日期：2026-09-04
- 基准：`E:\deepseek-harness`（TypeScript/Cordis 插件化 harness）
- 被对比：`E:\sp\ai`（OP 助手 Python 子模块）
- 来源：AUDIT-harness-alignment.md（含增量复核）+ 最新一轮独立探索代理对比（15 项差距）
- 用途：指导下一阶段对齐工作，每项完成后更新状态标注

> 状态标注：`[已闭合]` / `[部分闭合]` / `[未开始]` / `[外部阻断]`

## 一、状态校正（相对审计增量复核章节）

- **U7 MCP persistent stdio client：已闭合**（审计增量章节写作时未含）。`mcp/host.py` 已实现 per-(server, session) 持久客户端、initialize/initialized 握手、45s 超时、EOF/异常清理、配置指纹淘汰、`close_mcp_sessions_for_session` 批量关闭（接入 Agent `_run_post_chat`）。71/71 测试通过（`ai/mcp/tests/test_host_lifecycle.py` 4 项 + harness 套件）。
- **Sandbox 三入口统一：已闭合**。`h_run_shell`/`h_run_shell_command`/`_h_run_python_code` 均走 `run_shell_via_sandbox`/`run_python_via_sandbox`，session_id/cwd 透传。

## 二、剩余差距（按可落地优先级排序）

### P0 — 协议语义（可本地完成）

| # | 差距 | dsh 基准 | ai 现状 | 状态 |
|---|------|----------|---------|------|
| G1 | **Spill waterfall + content-block 语义**（= U3，任务 #46） | `packages/spill/spill-policy/src/index.ts:190-231`：`await next()` waterfall、只处理 accepted plain-text、跳过 nested PTC 的 model-facing arm、dispatch-log arm、UTF-8 head/tail retention、预留 notice 字节 | `core/agent/agent.py` 已注册 outermost waterfall；`tools/result_externalize.py` 提供纯文本 spill、UTF-8 head/tail、notice cap 预留；dispatch-log arm 仍待 PTC 接入 | `[部分闭合]` |
| G2 | **Goal/Plan/Todo event projection**（= U6） | `packages/goal/goal/src/domain.ts:13-114`：`goal/change` snapshot/tombstone 事件 + replay fold + scoped emit；plan/todo 同为 tool/domain event 投影 | `goal/store.py`、`plan/store.py`、`todo/store.py` 独立 JSON 快照，replay 无法重建 | `[未开始]` |
| G3 | **Compaction（会话压缩与 tool 结果修剪）** | dsh 有 compaction 语义：长会话上下文压缩、旧 tool 结果裁剪，保证 token 预算 | ai 无任何 compaction | `[未开始]` |

### P1 — 生命周期与错误契约（可本地完成）

| # | 差距 | dsh 基准 | ai 现状 | 状态 |
|---|------|----------|---------|------|
| G4 | **Agent 门面公开迭代接口**（= U13 的一部分） | public `wakeDriver()/whenIdle()` 生命周期驱动 | `core/agent/agent.py` 直接调私有 `loop._run()`，取消/唤醒/dispose 边界不一致 | `[未开始]` |
| G5 | **LSP structured error taxonomy + 取消 + 结果上限**（= U5） | `packages/lsp/*`：provider/extension 路由、60s tool budget、结果上限、`NO_PROVIDER/WORKSPACE_OUTSIDE/INVALID_RESPONSE` 错误码、取消升级终止进程 | `tools/harness_tools.py:339-375` 四操作可用但缺 provider 生命周期与结构化错误 | `[未开始]` |
| G6 | **Scheduler（agent 级 cron/at/every 工具）** | dsh 有 agent 级定时任务工具（at/cron/every） | ai 无 | `[未开始]` |
| G7 | **Subagent capability matrix + 父子 lineage**（= U9 剩余） | provider capability 声明、parentSession/delegationDepth/origin 持久化、depth/tool/outputSchema 能力拒绝 | `subagent/providers.py` registry 与并行 fan-out 已闭合；capability/lineage 缺 | `[未开始]` |
| G8 | **Profile patch composition**（= U12 剩余） | `packages/boot/app-boot/src/profile.ts`：ordered `dsh.profile.bundles`、`dsh.bundle.patch`、`cordis.patch.yml` 原子合成 | `bundle/` zip+manifest+原子安装已闭合；profile 层缺 | `[未开始]` |
| G9 | **U1 剩余细节**：完整 header 字段、ignorable event、全部 surface 细节核对 | `packages/core/session/src/types.ts:29-94,211-423` | 基础 strict event/surface 已落地（#34） | `[部分闭合]` |
| G10 | **U2 剩余细节**：完整 transcript/surface 语义、resume 后 loop 生命周期 | `packages/core/session/src/repair.ts` | repair closers 已落地（#33） | `[部分闭合]` |
| G11 | **U4 剩余**：SandboxPolicy session cwd/mode、可回放 runtime-context、host fallback 收敛 | `packages/sandbox/sandbox-policy/src/index.ts:1-130` | 三入口统一已闭合；session policy 缺 | `[部分闭合]` |
| G12 | **U13 剩余**：集中 config schema、依赖清单、启动诊断、边界错误稳定 code | 基准 Cordis inject/Schemastery Config | 靠 Params + try/except 静默回退 | `[未开始]` |

### P1 — 外部阻断（不可本地完成）

| # | 差距 | 阻断原因 |
|---|------|----------|
| G13 | MCP HTTP transport + bounded reconnect | 需真实第三方 MCP server 验证（U7 剩余） |
| G14 | 标准 ACP SDK adapter（Content-Length framing、permission/progress/cancel、resume repair） | 需标准 ACP SDK 依赖与对端联调（U8） |

### P2 — 增强（可本地完成但优先级低）

- G15 WorkflowEngine 脚本运行时语义（U10）
- G16 Skill scope/version/disposal 生命周期（U11 剩余）
- G17 远程 spill backend、LSP diagnostics/rename、MCP resources/prompts、workflow 可视化/模板市场

### 探索代理识别的其余差距（合并归类）

- Scheduler → G6；LSP taxonomy → G5；MCP HTTP/reconnect → G13；Compaction → G3；Agent facade → G4。
- 其余 10 项（attachment admission 严格化、PTC nested dispatch 等）均归入 G9/G1/P2 细节。

## 三、本轮推进计划

1. **G1 Spill waterfall**（engineer-general）→ #46
2. **G2 Goal/Plan/Todo event projection**（engineer-retry）
3. **G5 LSP error taxonomy + 取消 + 结果上限**（engineer-fix）
4. 完成后依次：G4 Agent 门面、G3 Compaction、G6 Scheduler
5. 每项完成 → 独立 QA 复核（qa-final）

## 四、边界说明（不得对外虚报）

- 本机无 scons、无 `cereal/gen/`、无 `libparams_c.so` → 不能构建完整 openpilot，只能针对 `ai/` 子模块用 pytest 验证。
- G13/G14 需外部环境，本地只能做代码层准备，不能声称"验证通过"。
- 严格协议/生命周期/恢复语义仍未全闭合前，不得声称"与 deepseek-harness 全语义对齐"。
