# GitHub Wiki 同步

Wiki 在线地址：https://github.com/mouxangithub/ai/wiki

源稿目录：**`docs/wiki/`**（与仓库同步维护，便于 PR 审阅）。

## 前置条件

GitHub Wiki 使用独立 git 仓库 `https://github.com/<owner>/<repo>.wiki.git`。若 clone 报 **Repository not found**，说明 **尚未启用 Wiki**：

1. 打开 https://github.com/mouxangithub/ai/settings  
2. **Features** → 勾选 **Wikis** → **Save**  
3. 再运行同步（见下）

> `GITHUB_TOKEN` 往往**无权**修改仓库 Features；CI 会 **跳过失败**（不标红 main）。若需全自动，在仓库 **Settings → Secrets** 添加 `WIKI_SYNC_TOKEN`（classic PAT，`repo` 权限）。

启用前，用户文档已在主仓可见：  
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
# Linux / macOS / 车机
bash ai/scripts/sync_github_wiki.sh
```

环境变量：`WIKI_REPO`（默认 `https://github.com/mouxangithub/ai.wiki.git`）。

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
