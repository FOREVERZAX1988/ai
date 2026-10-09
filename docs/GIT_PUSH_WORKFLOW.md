# Git 推送全流程（fork + 子模块）——发力点

> 目的：把「推送」的所有约定、坑、及子模块联动一次记清，避免每次重新摸索。
> 关联：`GIT_LFS.md`（LFS 细则与 PAT-helper 实战）、`GIT_PR.md`（提交与 PR）。

## 一、铁律（用户明确约定，不要再反复问）

1. **所有推送一律走 op助手 工具**（`git_push` / `publish_changes` / `git_publish_pull_request`）。
   凭据（GitHub PAT credential helper `/data/ai/bin/gh_credential.sh`，token 在
   `/data/ai/config.json` 的 `ai_github_actions_pat`）**已在 op助手 里配置好**，不要手动在
   shell 里临时填 token，也不要问用户要。
2. **必须绕开 LFS**：`GIT_LFS_SKIP_PUSH=1`（op助手 工具已默认加）。
   原因：fork 从 sunnypilot 公共 LFS 仓拉大文件，**不向 LFS 远端上传**（团队没有
   LFS 仓写权限，也不去动它）。
3. **必须带 `--no-verify`**：跳过 `pre-push` hook，避免 hook / LFS 校验阻断推送。

## 二、本机推送实测（无 SSH key，必须走 PAT-helper HTTPS 命令）

> ⚠️ **不要只看 `git_push` 是否可用**。本机**没有 SSH 私钥**，且全局 `.gitconfig` 有
> `pushInsteadOf` 把 `https://github.com/` 的推送改写成 SSH，导致默认路径一律
> `Permission denied (publickey)`。唯一好用的一键推送（PAT 不进 argv / 不留痕）：

```bash
# 在 /data/openpilot 下（父仓或各子模块目录内）
GIT_LFS_SKIP_PUSH=1 GIT_TERMINAL_PROMPT=0 git \
  -c credential.helper=/data/ai/bin/gh_credential.sh \
  push --no-verify \
  https://FOREVERZAX1988@github.com/FOREVERZAX1988/<repo>.git HEAD:<branch>
```

- `https://FOREVERZAX1988@github.com/...` 不含 `https://github.com/` 前缀，**不会被
  pushInsteadOf 改写**成 SSH。
- token 由 helper 提供，**不出现在命令行**。
- 显式 URL 推送**不会**自动更新 remote-tracking ref，推完 `git fetch origin <branch>`。

详细原理与修复见 `GIT_LFS.md`。

## 三、子模块单独推送（关键坑）

openpilot 是多仓结构。**父仓库的子模块指针（commit）指到子模块仓库里的某个 commit**，
推送要看两层：

1. **父仓库（openpilot）**：把 `gitlink` 指针提交并推送到 `FOREVERZAX1988/openpilot` 的
   `sp-macanlong-test`。
2. **每个子模块自己（ai / opendbc_repo / panda / webui 等）**：独立 git 仓库，各自有
   `origin`（`FOREVERZAX1988/<submodule>.git`）。父仓库指针指向的 commit，**必须已经推送到
   对应子模块的远端**，否则别人 clone 拉不到指针会坏。

### 核对本地 == 远端（含子模块）——用 git ls-remote 直接查远端真值

```bash
# 父仓库
git ls-remote origin refs/heads/sp-macanlong-test
# 各子模块（独立仓库，分别核对）
for sm in ai opendbc_repo panda webui; do
  echo "== $sm =="
  ( cd /data/openpilot/$sm && \
    echo "local  $(git rev-parse HEAD)"; \
    echo "remote $(git ls-remote origin refs/heads/sp-macanlong-test 2>/dev/null | awk '{print $1}')" )
done
```

本地 == 远端 = 已推送且一致；不等 = 该子模块的指针 commit 还没推到它自己的远端，需先分别推子模块。

> 注意：**不要只信本地 `origin/x` remote-tracking ref**（有时没 fetch 会误报 MISSING /
> 指向旧值）。以 `git ls-remote`（直接查远端）为准。

## 四、panda 专项（“不是说不动 panda 吗？” + tizi 判定）

这是合并上游时的常见疑问。结论与事实：

### 会不会动到 panda？
合并 upstream 时，panda 子模块指针会从旧 SHA 升到**上游 test 分支的 panda 指针**——跟随上游的必然动作。要确认是否「只跟上游」：
```bash
git ls-tree HEAD panda; git ls-tree upstream/test panda
```
两者相等 = 与上游一致，本地没额外改 panda。

### how to tell 改动是否影响 tizi/C3X（H7/cuatro）报错
tizi / C3X 的内置 panda 是 **H7/cuatro**；C3/tici 才是 **F4/dos**。判定：

- 上游 c3 类适配（如 `加强适配c3`，针对 F4/dos）凡会进 H7 的改动都要 `#ifdef STM32F4` 隔离，
  H7 侧保持 **byte-identical**。
- 仓库自带 `tests/h7_binary_parity.sh`：对比 base ref 的 H7 产物，证明某改动不改变 H7 固件。
- 关键判定：`grep -n STM32F4 board/drivers/fan.h` 等，确认新增代码是否 F4 专有。
- 现有 `board/obj/*/main.bin` 里烤入的 `gitversion`（如 `DEV-d84b110f-DEBUG`）反映当前源码状态。

判定一句话：**只有 F4/dos 改动、且经 h7_binary_parity 验证 → tizi/C3X 的 H7 固件与上游
逐字节一致，上车不会因 panda 改动报错。**

### ⚠️ 实测补充（2026-10-02，**push 前后都要核对**）
`加强适配c3` commit（`d84b110fc`）是**纯 F4/C3 适配**，且是「修复型」提交：

- `board/can_comms.h`：给 classic 构建的 `comms_can_write` 加**越界保护**（`tx_buffer_overflow`）
  和 `CANPACKET_DATA_SIZE_MAX` 边界判断，防止 F4 上 host/panda 包大小不一致导致的栈溢出。
  **该改动是安全修复，不是破坏** —— 正是之前上车报错（C3/F4 buffer overflow）的修复。
- `board/drivers/fan.h`：把上游删掉的 F4 fan stall 恢复逻辑用 `#ifdef STM32F4` 包起来，
  F4-only，H7 不受影响。
- `board/stm32f4/lldts.h`：新增 F4 温度传感器 stub（F413 无 DTS），纯 F4。
- 有 `tests/h7_binary_parity.sh` 可验证 H7 产物不变。

**结论**：当前 panda HEAD `d84b110fc 加强适配c3` ≠ 早期 pushed 的 `7d703710a 适配C3`
（早期版没有 can_comms 越界修复）。若当前 superproject 已把 panda 指向 `d84b110fc` 且已推送
到 panda 远端 `macanlong-test`，则 tizi 的 H7 固件不含越界修复路径（该修复是 F4 专用且更安全），
**正常不会因 panda 改动报错**。若担心，跑一次 `tests/h7_binary_parity.sh` 对照 base 确认 H7 无差异。

## 五、板上判定清单（先想清楚再动手）

1. 先 `git status`：父仓库是否 dirty；`git submodule status` 各子模块是否干净（无 `-`/`+` 前缀）。
2. 明确发布单元：openpilot 父仓 + 哪些子模块要一起推？**每个子模块单独推**（到各自的 origin）。
3. 推前 `git lfs push --dry-run` 应为 0。
4. 走 op助手 / PAT-helper HTTPS 命令推送（`GIT_LFS_SKIP_PUSH=1` + `--no-verify`），逐仓比对
   `git ls-remote`。
5. 推完**所有子模块 + 父仓库**后再整体 `git ls-remote` 复核一次一致性。