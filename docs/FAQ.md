# 常见问题（FAQ）

**Q: op助手和 comma 官方助手有什么区别？**  
A: 本仓库为社区 op助手，强调 openpilot 通用能力、技能/工具扩展、Cabana 与路线分析，不绑定单一 fork 品牌。

**Q: 必须联网吗？**  
A: 对话需要配置的 LLM API；车辆状态、Param、Cabana 等本地功能可离线使用（视部署而定）。

**Q: 行驶中能改参数吗？**  
A: 默认禁止。`safety-policy` 技能限制写操作；仅只读工具（如 `run_health_check`）可在行驶中使用。

**Q: 如何记住我的车型？**  
A: 首次向导或聊天中说明车型；也可写入 `vehicle_profile`（`POST /api/ai/memory`）。设置 → 平台可查看记忆。

**Q: Cabana 和官方 Cabana 一样吗？**  
A: Web 内嵌简化版：实时/回放、DBC 解码、曲线、CSV 导出、二进制视图；深度分析可走 AI 工具 `cabana_analyze`。

**Q: 健康检查会改我车吗？**  
A: 不会。`run_health_check` 与 `guide_ota_update` 均为只读汇总。

**Q: 技能太多怎么办？**  
A: 设置 → 技能：关闭不需要的；首次向导勾选的诉求会自动启用相关技能。

**Q: 更新 op助手 会覆盖我的配置、workspace、调参记录吗？**  
A: 正常 **`git pull` 不会**。`ai_*` 配置在 `/data/ai/config.json`（车机）或 `AI_CONFIG_PATH` 指定路径；`USER.md`、调参护照等在 openpilot 根目录，不在 `ai/` 代码树里。会被整目录替换的情况：① `ai/` 不是 git 安装（会备份为 `ai.bak.*` 后重新 clone）；② 执行卸载脚本删除 `ai/`。详见 [INSTALL.md — 更新/卸载与用户数据](INSTALL.md#user-data-persistence)。

**Q: 用 `.gitignore` 屏蔽 `prebuilt`、`ai_*` 够吗？**  
A: 够用于**避免误提交**，不能替代备份。`ai/.gitignore` 保护 `ai/data/` 等；openpilot 主仓建议额外忽略 `workspace/`、`adaptation_drafts/`。卸载或非 git 重装仍会删除 `ai/` 目录内数据。

**Q: op助手 能精通 Dragonpilot / sunnypilot / C2 等所有社区吗？**  
A: 定位为**通用助手**：安装时自动扫描当前 openpilot 分支与设备（C2/C3/C3X/C4），写入 `workspace/FORK_PROFILE.md`；常见社区在 `community_registry.json` 有匹配提示。配置 API 后可做 AI 全仓分析。不能离线背下所有 fork 的全部细节，但以**当前安装树 + 可选 Wiki RAG** 保持新鲜。见 [FORK_AND_COMMUNITY.md](FORK_AND_COMMUNITY.md)。

更多见 [QUICKSTART.md](QUICKSTART.md)、[CAPABILITIES.md](CAPABILITIES.md)、[INSTALL.md](INSTALL.md)、[FORK_AND_COMMUNITY.md](FORK_AND_COMMUNITY.md)。
