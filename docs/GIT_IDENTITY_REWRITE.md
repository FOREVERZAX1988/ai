# 提交身份重写：改掉设备默认署名，且不动别人的历史

> 场景：设备上的提交默认署名是 `Comma Device <device@comma.ai>`。要把**我们自己的**提交
> 改成 `FOREVERZAX1988`，同时**不能碰上游作者（mouxan）的历史**。2026-10-01 实测完成。

## 一句话做法

1. 先改**本地身份**：父仓库 + **每个子模块**的 `user.name/user.email`。只改历史不改身份，
   下次提交又会挂回设备名下 —— 这才是真正的"隐患"。
2. 历史改写用 `git filter-branch --env-filter`，并且**必须限定 rev 范围**。
3. 改写一定变 SHA → **父仓库的 gitlink 跟着改**，父提交信息里写死的 SHA 引用也要同步（否则文档自相矛盾）。
4. 推我们自己的 fork：`--force` + `--no-verify`（绕开 LFS pre-push 钩子）。

## 范围怎么选（最容易做错的一步）

```sh
# webui：基点选「别人的最后一个提交」
git -C webui filter-branch -f --env-filter "$ENVFILTER" -- 381be339..HEAD
#        ↑ mouxan 的 381be339 及更早因此原样保留（SHA 不变）
```

不加范围 = 整条线重写 = 把人家的历史也改了署名。子模块里判断"谁的是谁的"：
`git log --format='%h|%an <%ae>|%cn'`，只把**我们**的那些圈进范围。

```sh
ENVFILTER='
if [ "$GIT_AUTHOR_NAME" != "FOREVERZAX1988" ]; then
  export GIT_AUTHOR_NAME="FOREVERZAX1988"
  export GIT_AUTHOR_EMAIL="FOREVERZAX1988@users.noreply.github.com"
fi
if [ "$GIT_COMMITTER_NAME" != "FOREVERZAX1988" ]; then
  export GIT_COMMITTER_NAME="FOREVERZAX1988"
  export GIT_COMMITTER_EMAIL="FOREVERZAX1988@users.noreply.github.com"
fi'
export FILTER_BRANCH_SQUELCH_WARNING=1
```

## 校验清单（做完必须逐条跑）

| 检查 | 命令 | 期望 |
|---|---|---|
| 内容没丢 | `git diff <old-tip> <new-tip>` | **空**（tree 逐字相同） |
| 身份已换 | `git log --format='%an <%ae> \| %cn <%ce>' <base>..HEAD \| sort -u` | 只剩 FOREVERZAX1988 |
| message 没丢 | `diff <(git log --format=%s <old> -n) <(git log --format=%s <new> -n)` | 一致 |
| 日期保留 | `paste <(git log --format='%h %ad' <old>) <(git log --format='%h %ad' <new>)` | 逐条相同 |
| 范围外没动 | `git log --format='%h %an' -n3 <new>` | mouxan 的 SHA **原样** |
| 远端对得上 | `git ls-remote <url> refs/heads/<br> \| cut -f1` | 逐字 == 本地 HEAD |
| 推上去的确实是对的 | `git fetch <url> <br>:refs/tmp/verify` + `git ls-tree refs/tmp/verify ai webui .gitmodules` | tree 一致、gitlink 指向新 SHA |

> 改完父仓库还要 `git add ai webui`（更新 gitlink）+ `git commit --amend`，
> 否则别人 clone 到的还是旧指针。**commit message 里如果写了 SHA，也要一起改。**

## 本次实例（2026-10-01，FOREVERZAX1988）

| 仓库 | 分支 | 旧 SHA | 新 SHA |
|---|---|---|---|
| `openpilot` | `sp-macanlong-1001` | `485dfd8a1` | `8b6e29c63` |
| `ai` | `master-c3` = `sp-macanlong-1001` | `52beb3eb7` | `aeeccd8f2` |
| `webui` | `master-c3` = `sp-macanlong-1001` | `040a1b199` | `4d1c9a5b4` |

改写范围：ai 13 个提交（`origin/main..main`）、webui 2 个提交（`381be339..HEAD`）。
mouxan 的 `381be339`/`406cd29` 与 panda、opendbc、neural_network_data、第三方子模块**一律未动**。

备份（本地，可随时回退）：父仓库 `refs/backup/pre-submodule-reauth-super-1790859286`、
ai `refs/backup/pre-reauth-1790859286`、webui `refs/backup/pre-reauth-1790859286`。

## 两个坑

- **身份只写在本地 config**，不随提交分发 → 换设备/重刷后要重做一遍（否则又变 Comma Device）。
- `--force` 只允许对我们自己的 fork 分支用；`mouxangithub/*` 和 FZ 上别人已有的
  macan-long 线一律不碰（见 `GIT_PUSH_FOREVERZAX1988.md`）。

## 相关

- `GIT_PUSH_FOREVERZAX1988.md` — 推送到 FZ 的 `--no-verify` 配方与三个碰壁点
- `GIT_LFS.md` — LFS 拉取/不推送总策略
