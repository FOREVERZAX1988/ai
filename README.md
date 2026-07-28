# op助手（openpilot AI Agent）

面向 **comma 设备上各类 openpilot fork** 的通用 AI 助手：聊天调参、路线诊断、车辆适配、TSK SecOC、Cabana CAN 分析、社区 Wiki 知识库。

| 项目 | 说明 |
|------|------|
| 安装位置 | `<openpilot>/ai`（车机默认 `/data/openpilot/ai`） |
| Web 入口 | `http://<设备IP>:5090` |
| 配置 | 车机 `/data/ai/config.json`（无需编译 `params_keys.h`） |
| 集成 | 已内置于本仓库；`launch_chffrplus.sh` 自动启动 `aid` |

## 核心能力

- **通用 fork 感知** — 安装时扫描 `git remote`、目录与 Param 前缀，匹配 Dragonpilot / sunnypilot / FrogPilot / BluePilot / CarrotPilot 等（见 `fork/community_registry.json`）
- **安装即学习** — 写入 `ai_install_snapshot.json` 与 `workspace/FORK_PROFILE.md`；对话自动注入当前 fork/设备上下文
- **社区 Wiki → RAG** — 从 GitHub、Discourse 论坛、MediaWiki（wiki.gg）拉取文档入库，供对话检索
- **健康检查与分诊** — Engage、SecOC、Panda、指纹一键排查
- **Cabana 面板** — Web 内实时/回放 CAN 解码与导出
- **技能与插件** — 可扩展工具链（TSK、Sunnylink、GitHub CI 等）

## 快速开始

**车机（SSH）：**

```bash
curl -fsSL https://raw.githubusercontent.com/mouxangithub/ai/main/install/install.sh | bash
```

**PC：**

```bash
export OPENPILOT_ROOT=/path/to/openpilot
curl -fsSL https://raw.githubusercontent.com/mouxangithub/ai/main/install/install.sh | bash
cd "$OPENPILOT_ROOT" && python3 -m ai.aid
```

安装脚本会：克隆/更新 `ai/` → 注入 `launch_chffrplus.sh` → 运行 `integrate_openpilot`（含 fork 学习与 Wiki ingest）。

打开 `http://<IP>:5090` 完成首次向导（模型 API、车型等）。

## 常用命令

```bash
# 手动触发 fork 快照 + Wiki 同步
PYTHONPATH=$OPENPILOT_ROOT python3 -c "
from ai.fork.post_install import run_post_install_learn
print(run_post_install_learn())
"

# 强制重新拉取社区 Wiki
curl -X POST http://127.0.0.1:5090/api/ai/rag \
  -H 'Content-Type: application/json' \
  -d '{"operation":"wiki_ingest","force":true}'
```

## 文档

| 文档 | 说明 |
|------|------|
| [docs/README.md](docs/README.md) | **文档总索引** |
| [docs/INSTALL.md](docs/INSTALL.md) | 安装、集成、更新、卸载、数据持久化 |
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | 首次配置、快捷卡片 |
| [docs/FORK_AND_COMMUNITY.md](docs/FORK_AND_COMMUNITY.md) | 多社区 fork 检测、Wiki RAG、注册表 |
| [docs/CAPABILITIES.md](docs/CAPABILITIES.md) | 用户向能力速查 |
| [docs/FAQ.md](docs/FAQ.md) | 常见问题 |

**卸载：** `bash ai/install/uninstall.sh` — 见 [INSTALL.md#卸载](docs/INSTALL.md)。

## 设备支持

| 设备 | 说明 |
|------|------|
| C2 | comma two（Android）；部分 TSK/C3 工具不适用 |
| C3 / C3X / C4 | AGNOS + pandad；完整工具链 |
| PC | 开发与回放 |

详见 [docs/COMMA_DEVICES.md](docs/COMMA_DEVICES.md)。

## 仓库

- op助手：https://github.com/mouxangithub/ai
