# Git 推送全流程（fork + 子模块）——发力点

> 目的：把「推送」的所有约定、坑、及子模块联动一次记清，避免每次重新摸索。
> 关联：`GIT_LFS.md`（LFS 细则）、`GIT_PR.md`（提交与 PR）。

## 一、铁律（用户明确约定，不要再反复问）

1. **所有推送一律走 op助手 工具**（`git_push` / `publish_changes` / `git_publish_pull_request`）。
   凭据（GitHub PAT credential helper）**已在 op助手 里配置好**，不要手动在 shell 里临时填 token，也不要问用户要。
2. **必须绕开 LFS**：`GIT_LFS_SKIP_PUSH=1`（op助手 工具已默认加）。
   原因：fork 从 sunnypilot 公共 LFS 仓拉大文件，**不向 LFS 远端上传**（团队没有 LFS 仓写权限，也不去动它）。
3. **必须带 `--no-verify`**：跳过 `pre-push` hook，避免 hook / LFS 校验阻断推送。

> 等价手动命令（仅用户明确要求手动时才用）：
> ```bash
> GIT_LFS_SKIP_PUSH=1 git push --no-verify origin <branch>
> ```

## 二、op助手 推送工具的行为

| 工具 | 行为 |
|------|------|
| `git_push` | 自动 `GIT_LFS_SKIP_PUSH=1` + `--no-verify`（本机可能因无 SSH key 失败，见 GIT_LFS.md 的 PAT-helper 方案） |
| `publish_changes` | 对一个发布单元（openpilot / opendbc / assistant…）提交→推送→开 PR/MR |
| `git_publish_pull_request` | 提交本地改动、推分支、开 GitHub PR，自动在受保护 base 上建 `ai/*` 分支 |

## 三、子模块单独推送（关键坑）

openpilot 是多仓结构。**父仓库的子模块指针（commit）指到子模块仓库里的某个 commit**，推送到远端要看两层：

1. **父仓库（openpilot）**：把 `gitlink` 指针提交并推送到 `FOREVERZAX1988/openpilot` 的 `sp-macanlong-test`。
2. **每个子模块自己（ai / opendbc_repo / panda / webui 等）**：是**独立的 git 仓库**，各自有 `origin`（`FOREVERZAX1988/<submodule>.git`）。父仓库指针指向的那个 commit，必须**已经推送到对应子模块的远端**，否则别人 clone 出来拉不到子模块指针会坏。

### 检查本地 == 远端（含子模块）

```bash
# 在 /data/openpilot
# 父仓库
git rev-parse HEAD          # 本地
git ls-remote origin refs/heads/sp-macanlong-test   # 远端
# 各子模块（独立仓库，切换到各自目录核对）
for sm in ai opendbc_repo panda webui; do
  echo "== $sm =="
  ( cd /data/openpilot/$sm && \
    echo "local $(git rev-parse HEAD)"; \
    echo "remote $(git ls-remote origin refs/heads/sp-macanlong-test | awk '{print $1}')" )
done
```

三者相等 = 已推送且一致；不等 = 该子模块的指针 commit 还没推到它自己的远端，需先分别推送子模块。

> 注意：`@ {u}` / `origin/sp-x` 这类 remote-tracking ref 有时没 fetch，会误报 MISSING。核对远端请用 `git ls-remote`（直接查远端真值），不要只看本地 tracking ref。

### push 前检查 LFS 对象
```bash
git lfs push --dry-run origin HEAD   # 期望 0 个对象
```

## 四、panda 专项（“不是说不动 panda 吗？”）

这是合并上游时的常见疑问。结论与事实：

- **会不会动到 panda？** 合并 upstream 时，panda 子模块指针会从旧 SHA 升到**上游 test 分支的 panda 指针**——这是跟随上游的必然动作，不是本地乱改。要确认它是不是「只跟上游」：
  ```bash
  git ls-tree HEAD panda; git ls-tree upstream/test panda
  ```
  两者相等 = 与上游一致，本地没额外改 panda。

- **改了 panda 会不会影响 tizi（C3X）设备报错？**
  看改动是否影响 H7/`cuatro`（tizi/C3X 的内置 panda 是 **H7/cuatro**；C3/tici 才是 F4/dos）：
  - 上游 c3 类适配（如 `加强适配c3`，针对 F4/dos）通常所有会进入 H7 的改动都用 `#ifdef STM32F4` 隔离，H7 侧保持 **byte-identical**。
  - 仓库自带 `tests/h7_binary_parity.sh`，专门证明某改动不改变 H7 固件（对比 base ref 的 H7/panda_h7、body_h7、panda_jungle_h7 产物）。
  - 关键判定：`grep -n STM32F4 board/drivers/fan.h` 等，确认新增代码是否 F4 专有。
  - 现有 `board/obj/*/main.bin` 里烤入的 `gitversion`（如 `DEV-d84b110f-DEBUG`）能反映当前源码状态。

  判定一句话：**只有 F4/dos 改动、且经 h7_binary_parity 验证 → tizi/C3X 的 H7 固件与上游逐字节一致，上车不会因 panda 改动报错。**

## 五、板上判定清单（先想清楚再动手）

1. 先 `git status`：父仓库是否 dirty；`git submodule status` 各子模块是否干净（无 `-`/`+` 前缀）。
2. 明确发布单元：openpilot 父仓 + 哪些子模块要一起推？每个子模块单独推。
3. 推前 `git lfs push --dry-run` 应为 0。
4. 走 op助手 工具推送（LFS skip + `--no-verify`），逐仓比对 `git ls-remote`。
5. 推完全部（父 + 子模块）后再整体 `git ls-remote` 复核一次一致性。