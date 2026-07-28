# 文档索引

## 用户与部署

| 文档 | 说明 |
|------|------|
| [INSTALL.md](INSTALL.md) | 一键安装、openpilot 集成、更新、卸载、**用户数据持久化** |
| [QUICKSTART.md](QUICKSTART.md) | 首次配置、快捷卡片、Cabana 入门 |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Engage、网络、Cabana、日志排查 |
| [TUNING_GUIDE.md](TUNING_GUIDE.md) | 调参流程、技能与验证 |
| [FAQ.md](FAQ.md) | 常见问题（含 fork / 数据备份） |
| [CAPABILITIES.md](CAPABILITIES.md) | 用户向：op助手能做什么 |
| [OVERVIEW.md](OVERVIEW.md) | Web 功能、API 端点、参数说明 |
| [COMMA_DEVICES.md](COMMA_DEVICES.md) | C2 / C3 / C3X / C4、Panda / pandad 对照 |
| [PANDA_FLASH.md](PANDA_FLASH.md) | C3 DOS / 黑熊 F4 / 外接红熊 H7、多 Panda 刷机 |
| [GITHUB_RUNNER.md](GITHUB_RUNNER.md) | C3 自建 GitHub Actions Runner、prebuilt CI |

## 多社区与 Fork

| 文档 | 说明 |
|------|------|
| [FORK_AND_COMMUNITY.md](FORK_AND_COMMUNITY.md) | **通用 fork 检测**、注册表、`FORK_PROFILE.md`、**Wiki RAG ingest**（GitHub / Discourse / MediaWiki） |

## 架构与开发

| 文档 | 说明 |
|------|------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 模块结构、数据流（维护者） |
| [TSK_AND_AID.md](TSK_AND_AID.md) | aid 进程、TSK API、启动顺序 |
| [VEHICLE_ADAPTATION_GUIDE.md](VEHICLE_ADAPTATION_GUIDE.md) | 新车适配方法论 |
| [PLUGIN_DEV.md](PLUGIN_DEV.md) | 插件开发 |
| [SKILL_AUTHORING.md](SKILL_AUTHORING.md) | 技能编写 |
| [GIT_PR.md](GIT_PR.md) | 车机发 PR 工作流 |
| [PR_AUTOMATION.md](PR_AUTOMATION.md) | Actions 自动审阅/合并 |
| [UPSTREAM_SYNC.md](UPSTREAM_SYNC.md) | 与上游 openpilot 同步 |
| [SESSION_SYNC.md](SESSION_SYNC.md) | 会话同步 |

## 社区 Wiki 源（registry 摘要）

维护者在 `ai/fork/community_registry.json` 的 `wiki_repos` 中配置，运行时由 `wiki_ingest.py` 拉取：

| 社区 | 主要文档源 |
|------|------------|
| sunnypilot | [论坛文档区](https://community.sunnypilot.ai/c/documentation/114)（Discourse）、[user-docs](https://github.com/sunnypilot/user-docs)、sunnylink-wiki |
| Dragonpilot | [dragonpilot_wiki](https://github.com/dragonpilot/dragonpilot_wiki) |
| FrogPilot | [frogpilot.wiki.gg](https://frogpilot.wiki.gg/)（MediaWiki） |
| BluePilot | user-docs + 主仓 README/RELEASES |
| CarrotPilot | ajouatom/openpilot 主仓 |
| comma | GitHub Wiki（内置种子 + 可选拉取） |

支持的 `kind`：`repo`（默认）、`github_wiki`、`discourse`、`mediawiki`、`raw_file`。详见 [FORK_AND_COMMUNITY.md](FORK_AND_COMMUNITY.md)。

## 外部链接

- op助手仓库：https://github.com/mouxangithub/ai  
- TSK Web 上游：https://github.com/optskug/openpilot  
