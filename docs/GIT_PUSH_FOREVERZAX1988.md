# 推送到 FOREVERZAX1988（用 --no-verify 绕开 LFS）

场景：把本机 `master-c3` 的当前状态推到 `FOREVERZAX1988/<repo>` 下的一个**新分支**（如 `sp-macanlong-1001`），并且**不向 LFS 上传**。

## 一句话结论

用 `--no-verify` 绕开 pre-push 钩子（LFS 上传就在这个钩子里），并显式给**全 URL** + 带凭据的 gitconfig：

```sh
GIT_CONFIG_GLOBAL=/data/.gitcred/gitconfig GIT_TERMINAL_PROMPT=0 \
  git push --no-verify https://github.com/FOREVERZAX1988/<repo>.git <local-ref>:<new-branch>
```

## 为什么会碰壁

| 现象 | 根因 | 对策 |
|------|------|------|
| push 卡住 / 报 LFS 相关错误 / `Unprocessable entity` | 本仓 `.lfsconfig` 指向**上游 GitLab** `sunnypilot-new-lfs`，你没有自己的 LFS 上传仓；git-lfs 的 **pre-push 钩子**会尝试上传 LFS 对象 | `--no-verify` 绕过 pre-push。等价方案 `GIT_LFS_SKIP_PUSH=1` |
| `could not read Username` / 一直挂着等交互输入 | `fz` remote **没有**配在 `.git/config`（里面只有 `origin`=mouxangithub）；`refs/remotes/fz/*` 只是历史残留 | 直接推全 URL；`GIT_CONFIG_GLOBAL` 指向带 credential store 的 gitconfig，`GIT_TERMINAL_PROMPT=0` 让它是**快速失败**而不是挂死 |
| 子模块报 detached HEAD；或推到 `master-c3` 把别人的线覆盖了 | 子模块签出是 **detached HEAD**；`FOREVERZAX1988` 上 panda/opendbc/webui 已存在**分叉的** `master-c3`（macan-long 线），**不能覆盖** | 用显式 refspec `HEAD:refs/heads/<new-branch>`，并且用**新分支名**，别碰 `master-c3` |

> 关键：不要指望 `git config lfs.allowincompletepush true` 当万能解。它只让 Git 容忍 LFS 空指针，
> 真正的绕过点是 **pre-push 钩子**。

## 现成脚本

`/data/.gitcred/push-fz.sh`：

```sh
#!/bin/sh
# usage: push-fz.sh <repo> <local-ref>:<remote-branch>
set -e
export GIT_CONFIG_GLOBAL=/data/.gitcred/gitconfig GIT_TERMINAL_PROMPT=0
REPO="$1"; REF="$2"
git push --no-verify "https://github.com/FOREVERZAX1988/${REPO}.git" "$REF"
```

配套凭据（**不要**把 token 写进文档/日志）：

- `/data/.gitcred/gitconfig` — `credential.helper = store --file=/data/.gitcred/credentials`
- `/data/.gitcred/credentials` — `https://<token>@github.com`

## 本次实例：sp-macanlong-1001（2026-10-01）

```sh
# 主仓
/data/.gitcred/push-fz.sh openpilot master-c3:sp-macanlong-1001

# 子模块是 detached HEAD，必须给显式 refspec
cd /data/openpilot/opendbc_repo && /data/.gitcred/push-fz.sh opendbc HEAD:refs/heads/sp-macanlong-1001
cd /data/openpilot/webui        && /data/.gitcred/push-fz.sh webui    HEAD:refs/heads/sp-macanlong-1001
```

### 哪些子模块要推、哪些绝对不要推

| 子模块 | 推到 FOREVERZAX1988？ | 原因 |
|--------|----------------------|------|
| `openpilot`（主仓） | ✅ | 本次目标分支 |
| `opendbc_repo` | ✅ | 记录 gitlink `6580582c` |
| `webui` | ✅ | 记录 gitlink `381be339` |
| `panda` | ❌ | 记录 gitlink `4643ee2c` **已经在 `mouxangithub/panda:master-c3`**，无需重推；`FOREVERZAX1988/panda:master-c3`=`7d703710` 是**另一条 macan-long 线**，推过去会覆盖 |
| `ai` | ❌ | 记录 gitlink `48fa21ea` 在 `mouxangithub/ai` |
| msgq / rednose / teleoprtc / tinygrad | ❌ | 上游第三方，不是本 fork |

## 推完必须验证（别信“看起来成功了”）

```sh
export GIT_CONFIG_GLOBAL=/data/.gitcred/gitconfig GIT_TERMINAL_PROMPT=0
for r in openpilot opendbc webui; do
  echo "== $r =="
  git ls-remote "https://github.com/FOREVERZAX1988/$r.git" refs/heads/sp-macanlong-1001
done
```

远端 SHA 必须**逐字**等于本地对应 HEAD：

- `openpilot` → `git rev-parse HEAD`
- `opendbc` → `git -C opendbc_repo rev-parse HEAD`
- `webui` → `git -C webui rev-parse HEAD`

实测结果（全部命中）：

| 仓 | 远端 `sp-macanlong-1001` | 本地 |
|----|--------------------------|------|
| `FOREVERZAX1988/openpilot` | `9193f1e2c` | `9193f1e2c` ✅ |
| `FOREVERZAX1988/opendbc` | `6580582cc` | `6580582cc` ✅ |
| `FOREVERZAX1988/webui` | `381be3395` | `381be3395` ✅ |

## 相关文档

- `ai/docs/GIT_LFS.md` — LFS 拉取 / 不推送的总策略
- `ai/docs/PUBLISH.md` — 多仓发布（PR/MR）
- 技能 `git-lfs-fork`
