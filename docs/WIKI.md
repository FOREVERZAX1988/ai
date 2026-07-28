# GitHub Wiki 同步

Wiki 在线地址：https://github.com/mouxangithub/ai/wiki

源稿目录：**`docs/wiki/`**（与仓库同步维护，便于 PR 审阅）。

## 为什么 Wiki 网页能开，但 CI / git clone 仍失败？

| 现象 | 原因 |
|------|------|
| https://github.com/mouxangithub/ai/wiki 能打开 | Wiki **功能已开**，且可能已有**旧版**手写 Home 页 |
| `git clone .../ai.wiki.git` 报 Repository not found | **未登录**或 **Token 无权限** 时 GitHub 会返回 404（不是「没开 Wiki」） |
| 看不到 `docs/wiki` 里的新页面 | 同步脚本从未成功 push；线上仍是旧内容 |

**HTTPS 匿名 clone 经常失败**，需本机已 `gh auth login` / Git 凭据，或 CI 使用 `GITHUB_TOKEN` / Secret `WIKI_SYNC_TOKEN`（classic PAT，`repo`）。

## 前置条件

1. **Settings → Features → Wikis** 已勾选（你已完成）。
2. **Actions → Sync GitHub Wiki → Run workflow** 手动跑一次（推荐在启用 Wiki 之后）。
3. 若仍失败：添加 Secret **`WIKI_SYNC_TOKEN`**（PAT，`repo` 权限），再重跑 workflow。

启用前/同步失败时，文档已在主仓可见：  
https://github.com/mouxangithub/ai/tree/main/docs/wiki

## 自动同步
主仓 `main` 推送 `docs/wiki/**` 时，CI [sync-wiki.yml](../.github/workflows/sync-wiki.yml) 会尝试同步（Wiki 未启用则跳过）。

## 页面列表

| Wiki 页 | 源文件 |
|---------|--------|
| Home | `docs/wiki/Home.md` |
| Quick-Start | `docs/wiki/Quick-Start.md` |
| OP-CLI | `docs/wiki/OP-CLI.md` |
| Web-Terminal | `docs/wiki/Web-Terminal.md` |
| Tuning-for-Owners | `docs/wiki/Tuning-for-Owners.md` |
| Troubleshooting | `docs/wiki/Troubleshooting.md` |
| Vehicle-Adaptation | `docs/wiki/Vehicle-Adaptation.md` |
| Daily-Memory | `docs/wiki/Daily-Memory.md` |
| GEPA-Evolution | `docs/wiki/GEPA-Evolution.md` |

## 一键同步（推荐）

```powershell
# Windows（需已配置 git 凭据）
.\ai\scripts\sync_github_wiki.ps1
```

```bash
# 需已登录 GitHub（gh auth login 或 Git 凭据管理器）
bash ai/scripts/sync_github_wiki.sh
```

若仍报 `Repository not found`，请用 SSH 试一次：

```bash
git clone git@github.com:mouxangithub/ai.wiki.git
```

环境变量：`WIKI_REPO`、`WIKI_SYNC_TOKEN`（或 `GITHUB_TOKEN`）。

## 发布到 GitHub Wiki（手动）

GitHub Wiki 是独立 git 仓库：

```bash
git clone https://github.com/mouxangithub/ai.wiki.git
cd ai.wiki

# 从 openpilot/ai 仓库复制（路径按实际调整）
cp /path/to/openpilot/ai/docs/wiki/Home.md Home.md
cp /path/to/openpilot/ai/docs/wiki/Quick-Start.md Quick-Start.md
# … 其余页面

git add .
git commit -m "docs: sync OP Agent wiki from docs/wiki"
git push
```

首次需在 GitHub 仓库 **Settings → Features → Wikis** 启用 Wiki。

## 与 docs/ 关系

| 类型 | 位置 |
|------|------|
| 用户 Wiki | `docs/wiki/` → GitHub Wiki |
| 开发者长文 | `docs/*.md` |
| Issue/PR 模板 | `.github/` |

修改 Wiki 内容请编辑 `docs/wiki/` 后按上表同步，或在 PR 中一并提交源稿。
