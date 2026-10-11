# iOS `.ipa` 怎么生成 —— 有没有 Mac 都行吗？

> 适用范围：jetlink 的 iPhone/iPad 端（`jetlink` 仓库 `ios/`，共享 `JetlinkKit` SwiftPM 包）。
> 相关：`docs/releasing.md`（版本/回滚）、`docs/publishing.md`（发版流程）、
> `docs/iphone-app.md`（用户安装）、`ai/docs/JETLINK_WIFI_HANDSHAKE_ACCEPTANCE_1011.md`（设备验收）。
> 本文回答一件事：**一个可安装的 `Jetlink.ipa` 从哪来，没有 Mac 行不行。**

## 0. 一句话结论

**没有 Mac 也行，但前提不是 Mac，而是 Apple 付费会员 + 一把 Admin 角色的 App Store Connect 密钥。**
- 有 Mac：`make -C ios ipa`，产物落在 `ios/build/export/Jetlink.ipa`。
- 没有 Mac：走 GitHub Actions 的 **TestFlight** workflow（跑在 `macos-26` 上），
  取消勾选 `upload` 即只打包不发布，产物从该次 run 的 **Artifacts** 里下载（名 `Jetlink-ipa`）。
- 只有**免费** Apple ID（Personal Team）⇒ 出不了可分发的 `.ipa`，只能 7 天侧载，
  而且**还是得有一台 Mac + Xcode**。真正的门槛是钱和密钥，不是机器。

## 1. `.ipa` 是怎么造出来的

三步都在 `ios/scripts/testflight.sh` 里，`ios/Makefile` 只是包了一层：

| 步骤 | 命令 | 产物 |
|------|------|------|
| 生成工程 | `xcodegen generate`（读 `ios/project.yml`） | `ios/Jetlink.xcodeproj` |
| 归档 | `xcodebuild archive -scheme Jetlink -configuration Release` | `ios/build/Jetlink.xcarchive` |
| 导出 | `xcodebuild -exportArchive`（`method=app-store-connect`） | `ios/build/export/Jetlink.ipa` |

入口只有两个：

```bash
make -C ios testflight     # archive → 导出 → 上传 App Store Connect → 等 Apple 处理 → 发 TestFlight
make -C ios ipa            # 等价于 UPLOAD=0 的上面那条：只到导出，产出 .ipa，不上传
```

`make -C ios build` 和 `make -C ios typecheck` **不出 `.ipa`**：前者是 `CODE_SIGNING_ALLOWED=NO`
的编译验证，后者走 SwiftPM 只做类型检查——都没有签名，产物装不到手机上。

## 2. 路线 A：有 Mac

```bash
brew install xcodegen
cp ios/Config/Local.xcconfig.example ios/Config/Local.xcconfig   # 填 team 与 bundle id

JETLINK_TEAM=ABCDE12345 \
ASC_KEY_ID=XXXXXXXXXX \
ASC_ISSUER_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
ASC_KEY_PATH=$PWD/AuthKey_XXXXXXXXXX.p8 \
  make -C ios ipa
# 产物：ios/build/export/Jetlink.ipa
```

- 需要 Xcode 装了 **iOS 平台**（Xcode → Settings → Components），否则 device 构建直接失败。
- `Local.xcconfig` 已被 git 忽略；**不要**去动 Xcode 里的 Signing & Capabilities，
  那会把它写进受版本管理的工程文件。
- `make -C ios open` 打开工程，选好 team 后可以直接 Run 到手机上（这条路不需要 `ASC_*`）。

## 3. 路线 B：没有 Mac（GitHub Actions）

`jetlink` 仓库本来就带 `.github/workflows/testflight.yml`，`runs-on: macos-26`：

1. **Actions → TestFlight → Run workflow**，`upload` **不勾选**、选好分支 → Run。
   - 日志里会打印 `archiving and exporting only`。
2. 跑完在该次 run 底部 **Artifacts** 下载 `Jetlink-ipa`（内含 `Jetlink.ipa`）。
   - 这一步是本次新加的（见 §6）：以前 export-only 只是把 `.ipa` 留在临时 runner 上，
     run 一结束就连同机器一起销毁，等于拿不到。
3. 需要上传/发 TestFlight 时，把 `upload` 勾上，并按需填 `group`（`Public` = 公开链 + Beta App Review）。

**这条路的硬前提是仓库 secrets 齐全**，缺任何一个 workflow 会打印
`No APPLE_TEAM_ID or App Store Connect key: nothing goes to TestFlight` 然后什么都不做：

| secret | 是什么 |
|--------|--------|
| `APPLE_TEAM_ID` | Apple Developer 团队的 Team ID（10 位） |
| `NOTARY_KEY_ID` | App Store Connect API key 的 Key ID |
| `NOTARY_ISSUER_ID` | 该 key 的 Issuer ID |
| `NOTARY_PRIVATE_KEY_P8_BASE64` | `AuthKey_*.p8` 的 base64 |

**这把 key 必须是 Admin 角色**：脚本用 `-allowProvisioningUpdates` 让 `xcodebuild`
自己签发证书和描述文件（`ios/scripts/asc.py dev-certs`），跑完再把它本次造的开发证书吊销，
避免每次发布都在团队里留一张。

> 拿不到 `.ipa` 本体也没关系的情况：只是想让测试者装机，公开 TestFlight 链
> （`https://testflight.apple.com/join/DAsYk5sP`，见 `docs/iphone-app.md`）就够，不需要文件。

## 4. 路线 C：只想在真机上跑调试版

个人项目可以不开付费会员：用免费 Apple ID 的 **Personal Team** 在 Xcode 里 Run，
包 7 天过期、每台设备要单独信。但注意——**这条路仍然要一台 Mac + Xcode**，
而且产出的是开发包，不是可分发、可上传 TestFlight 的 `.ipa`。

## 5. 版本号与几个已知的坑

- **版本必须是纯 `X.Y.Z`**：`testflight.sh` 从 `jetlink/__init__.py` 读 `__version__`，
  带后缀（`0.8.0rc1`）会直接报错退出，因为 App Store 只收三段数字。
- **build 号默认是 commit 数**：`git rev-list --count HEAD`。同一个版本的 build 号
  App Store Connect 拒收重复，重传要用 `JETLINK_BUILD=…` 覆盖。
- **导出必须用系统 rsync**：脚本把 `PATH` 收成 `/usr/bin:…`，否则 Homebrew 的 rsync 3
  不认 Apple 的 `-E`，导出报 `Copy failed`（本地装了 Homebrew rsync 时就会踩）。
- **onnxruntime 的 `MinimumOSVersion`**：它是静态库，Info.plist 写的是 iOS 15.1，
  被 Xcode 链成动态 framework 后保留原值，App Store 会以 `ITMS-90208` 拒收；
  脚本按二进制真实的 `minos` 逐个改写（`vtool -show-build` → `PlistBuddy Set`）。
- **CI 上的 Xcode 版本**：由 `.github/actions/select-xcode` 固定（当前 26.6），
  runner 镜像丢掉该版本时会指名报错，而不是悄悄用默认版本。

## 6. 本次改动（2026-10-11）

| 仓库 | 文件 | 改动 |
|------|------|------|
| `FOREVERZAX1988/jetlink`（`cn`） | `.github/workflows/testflight.yml` | 新增 `Keep the exported .ipa`：export-only（`upload` 未勾选）时把 `ios/build/export/*.ipa` 作为 artifact `Jetlink-ipa` 留存 14 天 |
| `FOREVERZAX1988/jetlink`（`cn`） | `ios/Makefile` | 新增 `make -C ios ipa`（= `UPLOAD=0 testflight.sh`），把「只要 `.ipa` 不上传」变成一条命令 |

动机：验收文档里 "iOS / Mac 要真机生效得各自出包" 一直是待办，而现场没有 Mac。
补上 artifact 之后，**没有 Mac 也能从 CI 拿到那个待验收的 `.ipa`**。
