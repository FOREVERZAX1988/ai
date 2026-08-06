# op助手 目标架构（2026-08）

本文件描述 `ai/` 包的目标分层与迁移状态。旧 import 路径通过垫片（shim）保持兼容。

## 分层

```
aid.py                 # 唯一进程入口
server/                # HTTP/WS 传输层
core/                  # 平台内核（无 HTTP）
  llm/                 # client, model_accounts, model_router, embedding, usage
  chat/                # runner, jobs, compaction, command_queue, sanitize
  sync/                # hub, protocol, device_trust
  workspace/           # store, persona
  runtime/             # heartbeat, evolution_pipeline, sidecar_hub
services/              # 垂直业务能力
  cabana/              # CAN 面板后端
  tsk/                 # SecOC API
  panda/               # Panda 刷机路由
infra/                 # 基础设施门面
  auth/, config/, safety/, paths/, hardware/
integration/           # 外部系统集成（fork 等）
tools/                 # LLM 工具
  registry.py          # 元数据与 schema 门面
  executor.py          # 执行与审计
  domains/core/        # 物理分包（渐进）
agents/                # 多 Agent 编排
web/static/js/         # 前端
  app/                 # 全局注册与启动
  chat/                # 聊天 UI 模块
  sessions/            # （规划中）会话 store 迁移
```

## 依赖规则

1. `server` → `services` / `core` → `infra`
2. `core` 不 import `server`
3. `tools` 通过 `services.cabana.qlog_finder` 访问 Cabana，不 import `_private`
4. `scripts/` 仅运维入口，不作为库 import

## 迁移脚本

- `scripts/arch_migrate.py` — 根模块 → core/services/infra + 垫片
- `scripts/split_api_handlers.py` — 拆分 `server/handlers/api.py`

## 状态

| 阶段 | 内容 | 状态 |
|------|------|------|
| P0 | 目录骨架、文档、迁移脚本 | ✅ |
| P1 | api.py → 多 handler | ✅ |
| P2 | core/ + 根垫片 | ✅ |
| P3 | services/cabana | ✅（app 单体，qlog_finder 公开 API） |
| P4 | tools executor/registry + domains/core 样例 | ✅ |
| P5 | 前端 app/chat 模块 | ✅（渐进） |
| P6 | infra 门面、integration | ✅ |

## 后续

- 物理拆分 `services/cabana/app.py`（live/replay/routes）
- `tools/` 按 `domains/` 全量迁移
- `ai.js` 拆为 ES modules + esbuild
- RAG 静态数据外置 `data/rag/`
