# op助手 (ai) 架构说明

## 概览

`ai/` 是 comma 设备上 openpilot 树内的 LLM 助手子模块，提供 Web UI、工具调用、RAG、会话同步与车辆诊断能力。兼容各社区 fork，按当前安装树自动发现参数与 UI。

```
浏览器 (Vanilla JS)
    │  HTTP / WebSocket
    ▼
aid.py ──► chat_runner / agent_tools / session_store / sync_hub
    │
    ├── tools/          扁平工具注册（70+ 模块，按领域分子包是目标）
    ├── skills/         Markdown 技能与 RAG 种子
    ├── web/static/     前端资源
    └── tests/
```

## 前端模块

| 文件 | 职责 |
|------|------|
| `web/static/js/ai.js` | 主应用：聊天、设置、WebSocket、配置 |
| `web/static/js/sessions.js` | 本地 SessionStore（localStorage） |
| `web/static/js/session-sync.js` | 跨设备会话合并与冲突保护 |
| `web/static/js/model-combobox.js` | 模型输入：边输边模糊匹配下拉 |
| `web/static/js/local-prefs.js` | 配置草稿与模型列表缓存 |

### 会话同步（三层）

1. **localStorage** — 即时读写，单标签页主源
2. **Params (`session_store.py`)** — 车机持久化，上限 30 会话 × 100 条消息
3. **WebSocket (`sync_hub.py`)** — 多标签 / 多设备广播

合并策略见 `session-sync.js`：消息条数 → 内容体量 → `updatedAt`；本地流式输出或近期本地写入时暂缓远端覆盖。

### 模型选择 UX

所有模型字段统一使用 `ModelCombobox`：单一文本框 + 模糊匹配下拉，无需「手动 / 下拉」切换。首装向导在填写 API Key 后自动拉取 `/api/ai/models`。

## 多 Agent 编排（内置专员）

op助手采用 **主调度 + 预制专员**，用户只与「op助手」对话，系统自动派活。

```
用户消息 / 斜杠命令 / workflow
        │
        ▼
  agents/router.py  ──► 选定 agent_id + workflow
        │
        ├── filter_tools_for_agent()  收窄工具集
        ├── agent_system_prompt()     注入专员人设
        └── office.py                 工位状态 + 任务动态
        │
        ▼
  chat_runner.run_chat_loop()  （单 LLM 工具循环）
        │
        ▼
  SSE: agent_handoff | agent_status | tool_call | agent_done
```

**多域编排**（`agents/orchestrator.py`）：当 OP 路由且多个专员意图得分 ≥ 2.5 时，顺序委派最多 3 名专员（抑制子阶段 content 流），再由 OP 汇总 synthesis。SSE 额外事件：`orchestration_start`、`agent_summary`、`orchestration_synthesis`。

| 模块 | 路径 |
|------|------|
| 专员注册表 | `agents/registry.json` |
| 意图路由 | `agents/router.py` |
| 多域编排 | `agents/orchestrator.py` |
| 专员开关 | `agents/config.py` · `POST /api/ai/agents` |
| 办公室状态 | `agents/office.py` |
| 3D 动态场景 | `web/static/js/office-scene.js`（等距 Canvas，idle/派活动画） |
| 办公室 UI | `web/static/js/office-panel.js`（场景 + 专员列表 + 任务侧栏） |
| WS 广播 | `sync_hub.broadcast_office()`（多标签实时同步） |
| API | `GET/POST /api/ai/agents` |

内置专员：`op`（主调度）、`triage`、`tune`、`route`、`adapt`、`secoc`、`devops`、`cloud`、`pc`。

## 后端入口（当前）

| 文件 | 说明 |
|------|------|
| `aid.py` | 进程入口（~35 行），委托 `server/app_factory` |
| `server/app_factory.py` | 应用工厂、启动任务 |
| `server/handlers/` | REST 按域拆分（`chat_handlers`, `config_handlers`, …） |
| `server/handlers/_api_common.py` | 共享依赖与别名 |
| `server/deps.py` | Params、StateReader、JSON/SSE |
| `core/` | 平台内核：`llm/`, `chat/`, `sync/`, `workspace/`, `runtime/` |
| `services/` | 垂直服务：`cabana/`, `tsk/`, `panda/` |
| `infra/` | 配置/安全/路径门面 |
| `tools/registry.py` + `tools/executor.py` | 工具注册与执行 |
| `agents/` | 多 Agent 编排 |

根目录旧模块（如 `chat_runner.py`）为 **兼容垫片**，指向 `core/`。详见 [ARCHITECTURE_TARGETS.md](./ARCHITECTURE_TARGETS.md)。

### 前端模块

| 路径 | 职责 |
|------|------|
| `web/static/js/ai.js` | 主应用（逐步瘦身） |
| `web/static/js/app/globals.js` | `App` 命名空间 |
| `web/static/js/chat/model-tag.js` | 消息模型标签 |
| `web/static/js/sessions.js` | SessionStore |
| `web/static/js/session-sync.js` | 跨设备合并 |
| `web/static/js/web-chat-jobs.js` | 多会话 job 轮询 |

## 参考架构（历史）

| 文件 | 说明 |
|------|------|
| `chat_runner.py` | 垫片 → `core/chat/runner.py` |
| `session_store.py` | Params 会话读写（`tools/session_store.py`） |
| `sync_hub.py` | 垫片 → `core/sync/hub.py` |

详见 [OPENCLAW_LEARNINGS.md](./OPENCLAW_LEARNINGS.md)。

## 参考

- [OpenClaw](https://github.com/openclaw/openclaw) — Web UI 会话权威源与实时同步思路
