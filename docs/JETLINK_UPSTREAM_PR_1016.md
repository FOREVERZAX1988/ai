# Jetlink Android NPU —— 把 cn 交给上游（PR 准备 + 影响面）· 2026-10-16

> 用户两句：`jetlink这个做成pr推送给mouxangithub那边吧`、`A的话，对我们有什么影响吗？`
> 上一轮：`ai/docs/JETLINK_ANDROID_NPU_QNNSET_1016.md`（C：普通编译即 matched，cn `f5fe166`）

## 0. 分支状态（本轮实测，非记忆）

| 项 | 值 |
| --- | --- |
| 我们的 `cn` | `f5fe166`（= `origin/cn`，`git ls-remote` 核实；本地 remote-tracking 陈旧显示 ahead 2） |
| 上游 `mouxangithub/jetlink` `cn` | `9babbef`（2026-10-16 00:33 后未动） |
| 关系 | `git merge-base cn 9babbef` = `9babbef` ⇒ **上游是祖先，PR 可干净合并** |
| 差异 | 35 个提交（31 非 merge）、61 文件、+3211/−81，含 `android/app/src/main/jniLibs/arm64-v8a/` 五个二进制 |
| fork 关系 | `FOREVERZAX1988/jetlink` `fork=true`，parent = `mouxangithub/jetlink`（default `cn`）；仓库体积 77 MB vs 上游 32 MB |

## 1. PR 怎么提（API 走不通，用 compare 链）

`POST /repos/mouxangithub/jetlink/pulls` → **403 `Resource not accessible by personal access token`**。
原因：本机存的 `ai_github_actions_pat` 是 fine-grained（`github_pat_…`），而 fine-grained token 只能
访问「自己拥有/被邀请协作」的仓库，对 `mouxangithub/jetlink` 只有读权，拿不到 *Pull requests: write*。
**fork → 上游的 PR 本身是允许的**（公开仓任何人都能提），只是不能由这个 token 代提。

一次性链接（用 FOREVERZAX1988 登录的浏览器打开，`expand=1&quick_pull=1` 会直接展开填写页）：

```
https://github.com/mouxangithub/jetlink/compare/cn...FOREVERZAX1988:cn?expand=1&quick_pull=1
```

标题：`cn: the phone's own QNN set in the build, so a plain build opens an SM8975 Hexagon`
正文：`/data/jetlink-artifacts/pr-upstream-1016/pr_body.md`（同目录 `README.txt` 记了这条链与 403 原因）

正文里写明让上游拍板的两件事：① **签名**（上游没有 `043da762…` 那把 release keystore，
他编出来的 APK 装不上一加16，除非先卸载；要「他编的能直接装」= keystore 进他仓的 secrets）；
② **五个厂商二进制**（约 105 MB，`libQnnHtpPrepare.so` 84 MB；Qualcomm 许可只允许随 app 分发，
公开仓属于更宽的再分发；可改为 release 资产 + CI 下载）。

## 2. 对「我们」的影响（回答用户那句）

1. **不是保密问题**。这套 QNN 运行库确实到处都有（每台 SM8975 固件自带、QAIRT SDK 可下、
   Maven 上有到 V81 的 `qnn-runtime`）。用户说「本来这个库就是公开的」——对。
2. **真正的坑是「版本必须和设备对上」，不是「下不到」**。V85 这一代在公开渠道没有（Maven 止于 V81），
   这台机器又只认 **2.48.5**（2.51 的 Skel 要 priority token，被 DSP 拒）。所以「随便下个版本」必然踩坑，
   把**能用的那一套**放进仓库反而是在替别人省这个坑——这是我们做 C 的理由。
3. **风险点**：许可（再分发范围）+ 体积（GitHub >50 MB 告警、仓库从 32→77 MB）+ 上游未必收二进制。
   都不是「泄露」，最多是被要求撤下/重提；撤起来只是一次 revert。
4. **对「上游编出来能直接装」的影响 = 零帮助**：卡点不是库，是签名钥匙（见 §1①）。

## 3. 顺带两件实测记录

- **CI 并非全绿**：`f5fe166` = run `38837891307`，`Android app` / `App bundle and smoke test` /
  `Swift server for Android (libjetlink.so)` / `cn prerelease` **全过**（tag `0.8.7-1016-5`），
  但 `Swift build and tests`（`PageFeedTests` 时序断言）与 `Swift on Linux (x86_64)` 失败。
  查历史：`38821314003`（`bfcf7b9`）挂的是 `NewerCatalogTests`、`38815695268`（`10a3ce2`）挂的是
  `ProcessTests.sigtermStopsItCleanly`，每次都换测试 ⇒ **本 fork 的 Swift 套件一直有时序 flake**，
  与 Android/jniLibs 改动无关（`fa48c11` 那次全绿）。PR 正文按此如实写，不写「CI 全绿」。
- **/tmp 曾 100% 满**（150 MB tmpfs），工具写临时文件报 `No space left on device`。
  清掉的是可重生的分析临时件（`qnndiff/`、`qa/`、`ort.so`、V73/V81/V85 Skel 副本、`vm.apk`）；
  五个 2.48.5 真件仍在 `/data/media/qnn-v85-v248/` 与 `/data/jetlink-artifacts/work/_probe/`
  （且已进 git `f5fe166`）。`/data` 余 3.0 GB。

## 4. 本轮收口（2026-10-16 傍晚）：C 复核 + A 定稿（二进制留在 PR 里）

用户两句：`先做C再做A`、`五个二进制放PR一起推送吧`。

**C —— 复核为已成立（本机实测，非记忆）**

- 真仓库工作树是 `/data/openpilot/jetlink_repo`（`/data/openpilot/jetlink` 只是其中的
  `jetlink/` python 包软链；gitdir `/data/openpilot/.git/modules/jetlink`，`core.worktree=../../../jetlink_repo`）。
- `HEAD = f5fe166`，`git status` 干净；`android/app/src/main/jniLibs/arm64-v8a/` 五件在位，
  sha256 与 `JETLINK_ANDROID_NPU_QNNSET_1016.md` §1 表内五条**逐条相同**。
- `git ls-remote origin cn` = `f5fe166`（已推）。

**A —— 五个二进制确认真在远端（不是 LFS 指针）**

用 GitHub contents API 读 `FOREVERZAX1988/jetlink@cn` 那五个路径，回来的 size 与 blob sha：

| 文件 | size(read back) | blob |
| --- | --- | --- |
| `libQnnHtp.so` | 3,778,744 | `454efd18…` |
| `libQnnHtpPrepare.so` | 88,128,192 | `f97b092d…` |
| `libQnnSystem.so` | 4,052,904 | `db4221bb…` |
| `libQnnHtpV85Stub.so` | 779,448 | `e81e16db…` |
| `libQnnHtpV85Skel.so` | 12,582,764 | `2f0ce3aa…` |

与本地 `git ls-tree -l f5fe166` 的 blob 逐个一致 ⇒ **推送时没有被 `GIT_LFS_SKIP_PUSH` 掉成指针**
（`.gitattributes` 里对 `jniLibs`/`.so` 也无 LFS 规则）。PR 头分支的内容面至此齐了。

**PR 材料按「留」定稿**（`/data/jetlink-artifacts/pr-upstream-1016/`）：

- `pr_body.md`：第 2 条从「你说一声我们就撤下」改成「**我们有意留在这条分支里**」，
  把代价（约 105 MB、`libQnnHtpPrepare.so` 84 MB 超 GitHub 50 MB 告警、Qualcomm 许可属更宽再分发）
  和理由（`git clone` + `gradlew assembleRelease` 就该出能用的那一版）都写明，
  并保留「你若不愿背，我们改 release 资产 + CI 下载再 force-push」这句作为对方拍板的选项。
  另加一行实测：五件在分支上以真 blob 存在（附 size/blob），不是指针。
- `README.txt`：记同一条 compare 链、标题、以及 API 403。

**仍然卡在同一处（不是新问题）**：`POST /repos/mouxangithub/jetlink/pulls` 本轮再试仍
**403 `Resource not accessible by personal access token`**（`ai_github_actions_pat` 是 fine-grained，
对 `mouxangithub/jetlink` 无 *Pull requests: write*；读 `contents`/`refs` 正常 200）。
⇒ 开 PR 只有两条路：① 用 FOREVERZAX1988 登录的浏览器打开那条 compare 链；
② 换一个 classic PAT（`repo` 域）。**分支已推完，开 PR 是纯点击动作，不存在还没做的事。**
