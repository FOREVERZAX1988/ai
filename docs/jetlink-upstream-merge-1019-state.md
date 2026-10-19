# jetlink_repo 上游合并（sync/upstream-1019）中途状态 —— 2026-10-19 深夜

## 一、坐标
- 上游：`up` = https://github.com/mouxangithub/jetlink.git，`up/cn` tip = **39c555e0**
  （父仓 mouxangithub/openpilot `test` 的 gitlink 就是这个 sha）
- 我们：`sp-macan-test` tip = **7dfaa30**
- merge-base = **543258d**
- 增量：上游 86 提交 / 237 文件 / +42832 −2016；我们 84 提交 / 168 文件
- 文件级重叠 140，`git merge-tree` 预演 36 个真冲突（实际 merge 出 35）

## 二、为什么用 merge 而不是「文件级 cherry-pick」
上一轮父仓 26 文件增量可以用逐文件 cherry-pick，因为面小。jetlink 这轮 86 提交里
有一半是**不可拆的结构性改动**（`jetlink/openpilot/{hooks,stock,testing,events}.py`、
`docs/porting.md`、comment pass 全库重写、root 脚本搬进包内），逐文件挑会把
imports/测试互相扯断，所以本轮改成 **worktree 里真 merge，冲突逐个裁决**：

```
/data/openpilot/.jl-sync   ← 独立 worktree，分支 sync/upstream-1019，基线 7dfaa30
```
设备跑的还是 `jetlink_repo @ 7dfaa30`，**生产工作树没动**。

## 三、上游这轮到底改了什么（按价值排）
1. **lean-mici P0–P2（4cf01df）+ e3cad5b**：帧路径的 hold/预演调参从硬编码变成
   `hold_frame / settling_frames / holds_in_a_row` 三个可配参数 —— 也就是我们
   下午用手工 A/B 得出的那几个值，上游做成了通用实现。
2. **HEVC 帧路径**（bb2cc09 / acb69ee / 7e7e91d / 7525ac4 / df38e33 + `jetlink/hevc.py`、
   `jetlink/codecs.py`、`JetlinkKit/Sources/CHevc`、`jetlink_adapter` 的 V4L2 编码器 52d31c1d70）：
   393 KB/帧 降到 ~4 KB/摄像头，代价是有损。需要接收端 hello 里
   `frame_codecs` 支持，且要用户同意（`jetlink.codecs.pick`）。
3. **stages 运行记录（f154f8e）**：`stages.FrameStages` —— 六段
   `capture/warp/send/reply_wait/publish/overhead`，六段之和 = 帧周期，
   RING=1200，`summary(window)` 出 p50/p99/max。**这是我们的六段计时的上游版本**。
4. **fork 移植工具链**（约 50 提交）：`openpilot/hooks.py`（never-raise 门面）、
   `openpilot/stock.py`（Stock 基类）、`openpilot/testing.py`（`check_seam`/
   `check_fallback`/`FakeSubMaster`）、`openpilot/events.py`（SwapEvents）、
   `docs/porting.md`、CHANGELOG 的 API 版本规则、CI `upstream.yml`。
5. 健壮性：`NotFinite`（服务器返回 NaN → 当作 lag，不炸链路）、
   `model_state` 每次输出只求和一次、`ACTIVE_FRESH` 改成两个记录周期、
   warp 关掉 tinygrad compile pool、provision 先问线缆上的 host、server 在
   comma 安静 1 s 后预热、`comma/wifi.py` 的 mDNS 浏览（`_jetlink._tcp`）。
6. comment pass（6 提交，`say why, not when`）：全库注释重写，纯噪声但对
   merge 极不友好 —— 140 个重叠文件里大部分冲突来自它。

## 四、两套「六段」对比（结论：采用上游的）
| | 我们 caf0113 | 上游 f154f8e |
|---|---|---|
| 段 | pickup/warp/**pair/encode**/send/reply | capture/warp/send/reply_wait/publish/overhead |
| 校验 | 无（reply 由 client 回调补） | 六段之和 = 帧周期，能自证 |
| 环 | RING=64，KEPT=64（3 s 分位） | RING=1200（1 min）+ `summary(window)` |
| 接线 | `client.on_answer` 钩子 | 帧循环直接打点 + `joining.means()`/status |
| 测试 | 无独立用例 | `tests/test_stages.py` 222 行 |
**取舍**：用上游 `stages.py`（`git checkout --theirs`），我们的
pair/encode 细分并入上游的 `send` 段。代价是丢 lossless 打包/配对两段的粒度；
上游注释写明「加一个段是 additive」，将来真需要可以加 `encode` 打点。

## 五、已裁决的冲突（7 个，已 `git add`）
| 文件 | 裁决 |
|---|---|
| `jetlink/openpilot/stages.py` | **theirs**（见上表） |
| `jetlink/openpilot/status.py` | 两者都要：上游 `runtime()/Runtime()` + 我们 `unavailable(parts, record, mode)`（Wi-Fi 模式下不把 gadget 残留当失败） |
| `jetlink/openpilot/warp.py` | **theirs**：上游删了 compile-pool 预热（改成 init_device 关掉 pool），`prepare_reset` 上游版已覆盖我们「无 state_pairs + npy」的 fork 形态 |
| `jetlink/protocol.py` | 3 处都是上游纯新增（HEVC flag / HEVC_CODEC / NotFinite）→ 全取 theirs |
| `jetlink/comma/wifi.py` | 取上游 mDNS（`parse_browse`/`browse`/`discover(mdnss=)`) + 保留我们的 presence 数据报段（`PRESENCE_*`/`Presence`/`_message`/`_answered`）与 `json`/`os` import |
| `jetlink/openpilot/link.py` | 保留我们的 `BUILD_REFUSED`/`TargetCannotBuild`（Wi-Fi 建不出的模型本趟不再重试）+ 取上游的 Wi-Fi 拨号（gateway 先、mDNS 再、子网扫） |
| `scripts/comma/jetlink-root.sh` | **theirs**（变成 3 行转发器）；我们的 `FFS_LOG_OFF` 存在性保护已重新打回 `jetlink/comma/jetlink-root.sh`（`bash -n` 通过） |

## 六、还没裁决的 28 个（下一次从这里继续）
**核心 python（要读代码，不能机械取）**
- `jetlink/openpilot/model_state.py`（12 处）：上游 lean-mici 重写了 hold/预演，
  我们的 preview/六段/hold 都在同一段代码里 → 这是一切的地基，先做它
- `jetlink/openpilot/joining.py`（10 处）、`jetlink/client.py`（7 处）、
  `jetlink/comma/owner.py`（4 处）

**测试（依赖上面四个的裁决结果）**
- `tests/openpilot/{test_model_state,test_joining,test_api}.py`、
  `tests/test_comma_{owner,wifi}.py`（多数是双方各自新增，要「两边都留」；
  我们的六段/lossless 断言要跟着删）

**app 层（上游改了 UI/文案结构，我们是 zh-CN 文案 + 状态字段）**
- Android：`JetlinkApp.kt`、`ServerService.kt`、`Settings.kt`、`SettingsScreen.kt`、
  `StatusL10n.kt`(add/add)、`StatusState.kt`、`values/strings.xml`、
  `values-zh-rCN/strings.xml`(add/add)、`StatusStateTest.kt`
- iOS：`Views/Settings/SettingsScreen.swift`；`docs/android-app.md`

**Swift 包 / pin（上游把 make_pins 与 Pinned 重写了）**
- `JetlinkKit/Package.swift`、`Scripts/make_pins.py`、`Sources/JetlinkKit/Pinned.swift`、
  `Sources/JetlinkRegistry/LFS.swift`、`Sources/JetlinkServer/{EngineHost,Session,WireProtocol}.swift`、
  `Tests/JetlinkServerTests/ConformanceTests.swift`

## 七、验证口径（合完必须过）
```
cd /data/openpilot/.jl-sync && python3 -m pytest tests/ -x -q       # 上游这轮新增 ~25 个测试文件
git -C /data/openpilot/jetlink_repo rev-parse HEAD                  # 仍是 7dfaa30，生产未动
```
合完 & 测试绿之后才：push `sync/upstream-1019` → `sp-macan-test`，
父仓 bump gitlink，再处理父仓待办：`jetlink_adapter/__init__.py` 接线（我们 +104/−25 vs 上游 +7/−1）、
`opendbc_repo` +3 我们还没有的提交、`.gitmodules` 保持我们自己的 url/branch pin。

## 八、APK 结论（本轮不变）
app 侧这轮上游只有 UI 文案/设置项结构变化，**没有协议破坏性改动**，
所以现在的 apk 仍可对 `jetlink_repo@7dfaa30` 的 comma 跑；
等 Android 冲突落完、重新出包时再升级（HEVC 需要新 apk 才会走 `frame_codecs`）。

---

## 九、收尾记录（2026-10-19 22:30，本文所记的中途状态已全部落地）

上游 test `59efe220e6` 与 jetlink cn `39c555e` 的合入已提交，本文「28 待办」不再有效，
以本节为准。四条合并原则逐条落点：

| 层 | 谁赢 | 依据 |
|---|---|---|
| HEVC 载体（`hevc_venus.py` + `CHevc` + `stream.py` 头门） | 上游 | 唯一让「上路+弱 Wi-Fi」结构性成立的方案；适配器按上游接线 `hevc_encoder=hevc_venus.make_encoder` |
| 帧循环/降级（medium 决定循环、流水线不为自己等待、患者写、静默宽限、preview 落后帧 hold） | 我们 | 上游此层为空；合入时保留我们的策略做肉 |
| 诊断（`jetlink: stages` 行 = 验收脚本依赖） | 我们保留接口 | 上游分位 stages 进状态页并保留同一行文本（`model_state.py` 打印，`stages.py` 注释写明） |
| 迟到判定 | 上游 watermark + 我们的静默宽限 | 单比较替换调参窗，宽限只在链路整体静默时兜底 |
| 淡入 | 上游 | 叠加在我们的 `in_control` 安全门上（安全门不弃） |
| 就绪判定 | 上游 | `Status.read()` 先问 `unavailable()`（owner 活、warp 建好）再回答 ready，比只看 spec 的 ready 位更严 |
| 车型数据（opendbc） | 我们的 Macan 纵向 + 上游 mazda 两修 | 见父仓 `bbde8dbc0f` |

- 父仓：`43657ec00e`（jetlink 指针 → `bc70384` + venus 编码器接线）、
  `bbde8dbc0f`（opendbc → `ee86beb36`，mazda MADS 重新武装 / Oceania VIN；就绪测试跟上游语义）
- jetlink_repo：`bc70384`（上游 lean-mici 分层 + HEVC 载体 叠在我们的帧循环上）
- `.gitmodules`：保持 `FOREVERZAX1988/*` 与 `branch = sp-macan-test`，不取上游版本
- 已知未做/未动（非本次引入）：
  - `test_offline_it_is_tried_once_per_change`（1≠2）——10-17 已记录的离线重试去重漂移，
    要动的是 fetcher 的去重 memo 重置时机，单独一轮做
  - `car.capnp` 布局分叉：`activeCarrot/atcDistance` 我们在 `CarControl` 顶层 `@19/@20`，
    上游在 `HUDControl @11/@12`；`steerRatioV2 @80` 为 Macan PDS 本地字段
  - 手机 APK 仍是旧包：HEVC 要新包才会走 `frame_codecs`，旧包继续走无损路径，不阻塞

### 1️⃣ 真机验收口径（行车预览）
- 六段分布（pickup/warp/pair/encode/send/reply）已于 19:43–19:54 真机 PASS，451 条样本：
  车身侧 warp+pair+encode+send 合计 p50 = 11.3 ms，「链路慢」假设否掉；时间几乎全在 reply（手机侧推理）。
- 合入后本轮只做代码级闭环：`jetlink: stages` 打印点仍在（`model_state.py:742/750`）、
  `tests/test_stages.py` 21 passed、设备重启后 `jetlink_adapter` 正常起来（日志
  「nothing to provision」+「4 model(s) only newer catalogs list」、无异常）。
- 还差一次「合入后」的真机镜头链路采样（需要 行车预览 重开 + 手机 app 连上），
  采样命令：`grep -h 'jetlink: stages' /data/log/swaglog.* | tail -50`；
  无线地址实测：`192.168.10.65` 是一加16（SM8975，能跑大模型），`192.168.10.36` 是 Beam Pro
  （SM6450，engine 建不出来，只用来验 apk）。同 LAN 即可，不需要外网。
