# op助手（openpilot AI Agent）

面向 **comma 设备上各类 openpilot fork** 的通用 AI 助手：聊天调参、路线诊断、车辆适配、TSK SecOC、Cabana CAN 分析。

| 项目 | 说明 |
|------|------|
| 安装位置 | `<openpilot>/ai`（车机默认 `/data/openpilot/ai`） |
| Web 入口 | `http://<设备IP>:5090` |
| 集成 | 已内置于本仓库；`launch_chffrplus.sh` 自动启动 |

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

安装脚本会自动：克隆/更新 `ai/` → 注入 `launch_chffrplus.sh` → **ai 配置写入 `/data/ai/config.json`（无需编译 params_keys.h）**。

**卸载：** `bash ai/install/uninstall.sh` 或见 [docs/INSTALL.md](docs/INSTALL.md#卸载)。

**文档：** [docs/README.md](docs/README.md) · [INSTALL.md](docs/INSTALL.md) · [CAPABILITIES.md](docs/CAPABILITIES.md)
