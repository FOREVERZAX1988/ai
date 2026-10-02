# Git LFS 推送策略（fork）

用户在本 fork **推送代码**、发 PR、或问「push 失败 / LFS / Unprocessable entity」时启用。

> 完整说明：`ai/docs/GIT_LFS.md`（含本机凭据实测）

## 策略（必须遵守）

1. **拉取**：`git lfs pull` 从 `.lfsconfig`（GitLab sunnypilot-new-lfs）拉大文件 — **正常执行**
2. **推送**：**统一用 op助手 推送**，凭据已配好；**不向 LFS 上传** — 使用 `GIT_LFS_SKIP_PUSH=1`
3. **推送带 `--no-verify`**：跳过 pre-push hook
4. **自改 UI 字体/训练图**：已在 `.gitattributes` 排除 LFS，走普通 Git

## 用户约定（记住，不要再反复问）

- **推送一律用 op助手**（`git_push` / `git_publish_pull_request` / `publish_changes`），
  **不要**手动 shell `git push`。
- **密钥已在 op助手 内配置好** — 不需要向用户索要 token / 凭据。
- **绕开 LFS 文件** + **`--no-verify`** 是默认动作，直接照做即可。

## op助手 行为

- `git_push`、`git_publish_pull_request`、`publish_changes` **已自动** `GIT_LFS_SKIP_PUSH=1` 并走 `--no-verify`
- 用户手动 shell push 时，提醒 `--no-verify` 与 `GIT_LFS_SKIP_PUSH=1`

## ⚠️ 本机实测（2026-10-02）：默认路径会失败，先看这里

`git_push` / `git push origin` 在本机**报 `git@github.com: Permission denied (publickey)`**，
因为：本机无 SSH 私钥，而全局 gitconfig 有 `pushInsteadOf = https://github.com/` →
把推送地址改成 SSH。op助手 的凭据是 **PAT helper** `/data/ai/bin/gh_credential.sh`
（读 `/data/ai/config.json` 的 `ai_github_actions_pat`），但**未写入任何 git config**。

**已验证可用的一键推送**（PAT 不进 argv）：

```bash
GIT_LFS_SKIP_PUSH=1 GIT_TERMINAL_PROMPT=0 git \
  -c credential.helper=/data/ai/bin/gh_credential.sh \
  push --no-verify \
  https://FOREVERZAX1988@github.com/FOREVERZAX1988/openpilot.git HEAD:<branch>
git fetch origin <branch>   # 显式 URL 推送不会自动更新 remote-tracking ref
```

（`https://<user>@github.com/...` 不匹配 `https://github.com/` 前缀 → 不会被改写成 SSH。）
**先试 `git_push`；只有它报 publickey 时才用这条，并在回复里说明。**

## 推送前（AI 应做）

```
git_status → git_diff
git lfs push --dry-run origin HEAD   # 应为 0 个上传对象
git_push / git_publish_pull_request(confirm=true)
```

## 用户手动命令（仅用户明确要求时）

**CMD**

```cmd
set GIT_LFS_SKIP_PUSH=1
git push --no-verify origin master-c3
```

**PowerShell**

```powershell
$env:GIT_LFS_SKIP_PUSH=1
git push --no-verify origin master-c3
```

**持久（本仓）**

```bash
git config --local lfs.allowincompletepush true
```

## 常见错误

| 错误 | 处理 |
|------|------|
| `git@github.com: Permission denied (publickey)` | 无 SSH key + `pushInsteadOf` 改写 → 用上面的 PAT-helper HTTPS 命令 |
| LFS upload `Unprocessable entity` | 用 op助手推送（自动 `GIT_LFS_SKIP_PUSH=1`）；手动则先设环境变量 |
| `pre-push` hook 阻断 | 加 `--no-verify` |
| push 含新 LFS 指针 | 改为普通 Git 或不要提交大文件到 LFS 跟踪路径 |
| CI `git lfs pull` 失败 | 检查 runner 能否访问 `.lfsconfig` URL |

## 禁止

- 未经用户明确要求，不要设 `GIT_LFS_SKIP_PUSH=0` 上传 LFS
- 不要把密钥写进 `.lfsconfig` pushurl 来「绕过」权限
- 不要把 PAT 明文写进命令行 / 日志（走 `gh_credential.sh`）

## 相关

- 技能 `git-pr-workflow`
- 文档 `ai/docs/GIT_LFS.md`
