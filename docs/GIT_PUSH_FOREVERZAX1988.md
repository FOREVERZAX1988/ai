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

---

# 第二批：推到同名分支 master-c3（2026-10-01）

上一批用的是新名字 `sp-macanlong-1001`。这一批按用户要求推到**同名分支 `master-c3`**，
并解决 ai 子模块的归属问题。新增 3 个碰壁点：

## 碰壁点 1：token 属于 FOREVERZAX1988，推 mouxangithub 必然 403

```
remote: Permission to mouxangithub/ai.git denied to FOREVERZAX1988.
fatal: unable to access 'https://github.com/mouxangithub/ai.git/': The requested URL returned error: 403
```

`/data/.gitcred/credentials` 里的 token 是 **FOREVERZAX1988** 账号的。
所以 ai 子模块**不能**推到 `mouxangithub/ai`（不管"权限打没打开"，那是账号层面的写权限）。
→ 改推 `FOREVERZAX1988/ai`。**先跑一次 `git ls-remote` 探所有权，别等 push 报 403 才发现。**

## 碰壁点 2：FZ/ai 的 main 已分叉，不要硬推 main

- `FOREVERZAX1988/ai:main` = `2d0ac95` — 提交信息 `Merge branch 'mouxangithub:main' into main`，比 `48fa21e` 多 **27** 个提交
- 本地 ai = `59e1a7c` = `48fa21e` + 1
- 两侧都以 `48fa21e` 为基点 → **非快进**，`--force` 会抹掉别人 27 个提交

对策：推**同名新分支**（远端不存在 → 天然不覆盖）：

```sh
cd /data/openpilot/ai
GIT_CONFIG_GLOBAL=/data/.gitcred/gitconfig GIT_TERMINAL_PROMPT=0 \
  git push --no-verify https://github.com/FOREVERZAX1988/ai.git main:refs/heads/master-c3
# 已存在的分支：先 git ls-remote 确认远端 SHA，再决定是否复用
```

## 碰壁点 3：.gitmodules 不同步改，新分支 clone 时子模块会断

`webui` 上一批已指到 `FOREVERZAX1988/webui`，但 `ai` 还指着 `mouxangithub/ai`。
于是 `clone FZ/openpilot:master-c3` + `git submodule update` 会在 ai 上失败（那个 SHA 在 mouxangithub/ai 里不存在）。
**推完子模块必须把 .gitmodules 一起指过去**，否则分支看起来完整、实际拉不全。

```diff
 [submodule "ai"]
 	path = ai
-	url = https://github.com/mouxangithub/ai.git
+	url = https://github.com/FOREVERZAX1988/ai.git
+	branch = master-c3
```

改完执行 `git submodule sync ai`，让本机 `.git/config` 也跟上（否则本机仍在用旧 URL）。

## 本次实例：master-c3

```sh
# 1) ai 子模块 → 你自己的 ai 仓库（同名新分支）
cd /data/openpilot/ai
GIT_CONFIG_GLOBAL=/data/.gitcred/gitconfig GIT_TERMINAL_PROMPT=0 \
  git push --no-verify https://github.com/FOREVERZAX1988/ai.git main:refs/heads/master-c3

# 2) 改 .gitmodules 指向 + sync + 提交
#    chore(submodules): point the ai submodule at FOREVERZAX1988/ai branch master-c3

# 3) 主仓
/data/.gitcred/push-fz.sh openpilot master-c3:master-c3
```

实测对照（远端 SHA **逐字**等于本地）：

| 仓 | 远端分支 | 远端 SHA | 本地 SHA | 结果 |
|----|----------|----------|----------|------|
| `FOREVERZAX1988/openpilot` | `master-c3` | `39e1ff086` | `39e1ff086`（HEAD） | ✅ |
| `FOREVERZAX1988/ai` | `master-c3` | `59e1a7cef` | `59e1a7cef` | ✅ |
| `FOREVERZAX1988/webui` | `master-c3` | `381be3395` | `381be3395` | ✅（已存在，无需重推） |
| `mouxangithub/opendbc` | `tn-c3` | `6580582cc` | `6580582cc` | ✅（.gitmodules 就指它） |
| `mouxangithub/panda` | `master-c3` | `4643ee2c6` | `4643ee2c6` | ✅（.gitmodules 就指它） |

### 这两个绝对不要往 FZ 的同名分支推（会覆盖别人的 macan-long 线）

| 仓 | 远端 master-c3 | 本地 | 原因 |
|----|----------------|------|------|
| `FOREVERZAX1988/opendbc` | `a315728` | `6580582c` | 不是一条线；本地 SHA 已在 `mouxangithub/opendbc:tn-c3` |
| `FOREVERZAX1988/panda` | `7d703710` | `4643ee2c` | 同上；本地 SHA 已在 `mouxangithub/panda:master-c3` |

> 判断法则：**子模块的 .gitmodules url 指哪个仓，就把那个仓当作它的家。**
> 只有在"这个仓里根本没有那个 gitlink SHA"时才需要另找地方推。

## 验证清单（每次推完都跑）

```sh
export GIT_CONFIG_GLOBAL=/data/.gitcred/gitconfig GIT_TERMINAL_PROMPT=0
git rev-parse HEAD                      # 主仓
git -C ai rev-parse HEAD                # ai
git -C webui rev-parse HEAD             # webui
# 逐个比对
git ls-remote https://github.com/FOREVERZAX1988/openpilot.git refs/heads/master-c3
git ls-remote https://github.com/FOREVERZAX1988/ai.git        refs/heads/master-c3
git ls-remote https://github.com/FOREVERZAX1988/webui.git     refs/heads/master-c3
```

**远端 SHA 必须逐字等于本地 HEAD**；只看到 `* [new branch]` 不算成功。

## 相关文档

- 上批（`sp-macanlong-1001`）见本文上半部分
- `ai/docs/GIT_LFS.md` — LFS 拉取 / 不推送的总策略

---

# 第三批：重推 sp-macanlong-1001（含 ai 子模块**同名**分支，2026-10-01）

背景：批一建过 `sp-macanlong-1001`，但只到 `9193f1e2c`。之后 `master-c3` 上又落了 3 个提交
（`c45e6e246 / 39e1ff086 / 54f5956cc`，ai 子模块指针 + 知识库），而且 **ai 子模块里还有未提交的
工具修复**（`system/paths.py`、`tools/domains/core/diagnostics_tools.py`）。所以这一批的实质是
"先提交、再重推、子模块也同名"。

## 顺序（照抄）

```sh
# 1) 先提交**子模块内部**的改动 —— 不提交的东西永远不会被 push 带上去
cd /data/openpilot/ai && git status --short          # 必须为空才算干净
git add -A && git commit -m "fix(tools): ..."

# 2) 子模块推同名分支（远端没有 → 新建，不会覆盖别人的线）
/data/.gitcred/push-fz.sh ai HEAD:refs/heads/sp-macanlong-1001

# 3) 主仓 bump gitlink + 提交
cd /data/openpilot && git add ai && git commit -m "chore(ai): bump the ai submodule ..."

# 4) 主仓推同名分支（批一已建过 → 这是**快进**，不要 --force）
/data/.gitcred/push-fz.sh openpilot HEAD:refs/heads/sp-macanlong-1001

# 5) 逐字核验
for r in openpilot ai webui; do
  echo "== $r"; git -C /data/openpilot${r/ai/\ai} rev-parse HEAD
  GIT_CONFIG_GLOBAL=/data/.gitcred/gitconfig GIT_TERMINAL_PROMPT=0 \
    git ls-remote "https://github.com/FOREVERZAX1988/$r.git" refs/heads/sp-macanlong-1001
done
```

## 本批新增的 3 个碰壁点

| 现象 | 根因 | 对策 |
|------|------|------|
| "改完了"却推不上去 / 远端还是旧 SHA | `git status` 里的 ` M ai` **只是 gitlink 脏**；子模块**内部**的未提交改动根本不参与 `git push` | push 前 `git -C <submodule> status --short` 必须干净；先提交子模块，再 bump gitlink |
| 子模块分支名和主仓不一致 → 别人 clone 这条线时子模块拉不全 / `--remote` 拉到旧内容 | `.gitmodules` 里 `ai` 的 `branch = master-c3`，而这次推的是 `sp-macanlong-1001` 分支 | **同名推**（`HEAD:refs/heads/sp-macanlong-1001`）之外，再把子模块的 `master-c3` 也**快进**到同一个 SHA，让两条线不打架 |
| 分支已存在（批一建的） | `sp-macanlong-1001` 不是新分支 | 直接 push（本地 HEAD 是远端 SHA 的后代 → 快进）；**不要** `--force`，否则会丢掉批一之后别人可能推的东西 |

> 验证口径不变：**远端 SHA 必须逐字等于本地 HEAD**。只看到 `Everything up-to-date` 或
> `* [new branch]` 都不算成功 —— 尤其要注意"推了主仓但没推子模块"这种看着成功的假成功。

## 实测对照（第三批，全部逐字命中）

```sh
git push --no-verify https://github.com/FOREVERZAX1988/ai.git        HEAD:refs/heads/sp-macanlong-1001 HEAD:refs/heads/master-c3
#    50f0c0c..e52d213  HEAD -> master-c3        |  * [new branch]  HEAD -> sp-macanlong-1001
git push --no-verify https://github.com/FOREVERZAX1988/openpilot.git HEAD:refs/heads/sp-macanlong-1001 HEAD:refs/heads/master-c3
#    54f5956cc..ee2362b18  HEAD -> master-c3     |  9193f1e2c..ee2362b18  HEAD -> sp-macanlong-1001
```

| 仓 | 分支 | 远端 SHA | 本地 SHA | 结果 |
|----|------|----------|----------|------|
| `FOREVERZAX1988/openpilot` | `sp-macanlong-1001` | `ee2362b18` | `ee2362b18` | ✅ **快进**（批一 `9193f1e2c` → 本次），未用 `--force` |
| `FOREVERZAX1988/ai` | `sp-macanlong-1001` | `e52d213c` | `e52d213c` | ✅ 新建 |
| `FOREVERZAX1988/webui` | `sp-macanlong-1001` | `381be3395` | `381be3395` | ✅ 本来就对，未重推 |
| `FOREVERZAX1988/openpilot` | `master-c3` | `ee2362b18` | `ee2362b18` | ✅ 顺手快进，两条线同 SHA |
| `FOREVERZAX1988/ai` | `master-c3` | `e52d213c` | `e52d213c` | ✅ 顺手快进（让 `.gitmodules` 的 `branch=master-c3` 不再指向旧内容）|

**没碰的（故意）**：`FOREVERZAX1988/opendbc:master-c3`=`a315728585`、
`FOREVERZAX1988/panda:master-c3`=`7d703710a8` —— 别人的 macan-long 线，推过去就是覆盖。

> 本批 `--no-verify` 全部一次通过、**没有任何 LFS 报错**，再次印证：绕过点是 pre-push 钩子。

## 相关文档

- 上两批见本文上半部分
- `ai/docs/GIT_LFS.md` — LFS 拉取 / 不推送的总策略
- `ai/docs/UI_FREEZE_WEBUI_BLOCKING.md`、`ai/docs/DEVICE_LOG_PATH.md` — 本批 ai 子模块里带的两条修复知识

## 第四批：同一次会话里的后续提交（2026-10-01）

批三推完之后，同一个会话又落了两批修复（cereal 导入布局 → 状态读恢复、
配置原子写并发 → 建会话 500、chat_status schema → WS 丢帧）与对应文档，
再按**完全相同的顺序**推了一次（子模块 → 主仓，都是快进，`--no-verify`）：

| 仓 | 分支 | 推前 | 推后 |
|----|------|------|------|
| `FOREVERZAX1988/ai` | `sp-macanlong-1001` / `master-c3` | `3502223` | `e8eae71b6` |
| `FOREVERZAX1988/openpilot` | `sp-macanlong-1001` / `master-c3` | `193e22b7d` | `e6b887d97` |
| `FOREVERZAX1988/webui` | `sp-macanlong-1001` | `381be3395` | 未变（无需重推）|

> **注意**：所以批三表里那些 SHA 是**当时**的中间值，不是"最终值"。
> 想知道当前线上是什么，永远以 `git ls-remote` 现场查为准，别抄文档里的历史 SHA。

## 坑：不带 `--no-verify` 的 push 会留下**挂死几小时的孤儿进程**

2026-10-01 实测：06:24:21 起的 `git push --progress https://…/FOREVERZAX1988/openpilot.git master-c3:master-c3`
**没有** `--no-verify`，于是 pre-push 钩子照跑，整条链挂死 **1 小时 49 分**：

```
git push → git-remote-https → .git/hooks/pre-push
  → git lfs pre-push → git-lfs pre-push
  → ssh -oControlMaster=yes … git@gitlab.com git-lfs-transfer /sunnypilot/public/sunnypilot-new-lfs.git upload
```

而**推送其实早就成功了** —— `git ls-remote` 显示远端 `master-c3` / `sp-macanlong-1001`
都已是期望的 SHA。挂着的只是 LFS 上传的孤儿进程（在后台白烧 CPU/IO）。

### 教训（三条）

1. **一律带 `--no-verify`**（或 `GIT_LFS_SKIP_PUSH=1`）；本仓 `.lfsconfig` 指向上游 GitLab，你没有上传仓。
2. **判断"推没推上去"要用远端事实，不要用进程还在不在**：
   ```sh
   git ls-remote --heads https://…/FOREVERZAX1988/openpilot.git master-c3 sp-macanlong-1001
   ```
   进程还在 ≠ 没推完；进程没了 ≠ 推成功。
3. **清理孤儿**（先确认远端已有该 SHA，再杀）：
   ```sh
   ps -eo pid,lstart,args | grep -E "git push|git-lfs|git-lfs-transfer"
   kill <push-pid> <lfs-pids> <ssh-pid>
   ```
