# JetLink —— B/D/C 落地：响应只有 8 KB（B 的前提是错的），Wi-Fi 锁与 preview 流水线已进补丁（2026-10-17）

> 设备 `comma-a821bfb2`（tizi，Porsche Macan）｜jetlink `cn` `60ed27b` → 本轮 +2 提交（未推）
> 上一轮：`ai/docs/JETLINK_PIPELINE_1016.md`（8e6 的三处串行）、`ai/docs/JETLINK_WIFI_FPS_1016.md`（帧预算）
> 手机：一加16（PYB110 / SM8975 / Android 17）｜无线 adb 已配对成功并持久化（`/data/ai/adb/`）

## 0. 结论先说

| 项 | 结果 |
| --- | --- |
| **B（响应量化/压缩）** | **前提是错的，不建议落地**。响应不是 73.8 KB 而是 **8,292 B**：`hidden_state`（16384/18452 个 float）按 protocol v3 留在手机上，下行的只是 `outputs` 的 2068 个 float。改成 f16 只省 4,146 B ≈ 0.4 ms/帧（Wi-Fi 实测吞吐 8–13 MB/s 下），对 ~54 ms 的帧周期是 **<1%**，却要动协议（flag + hello 能力 + 两端解码 + conformance 夹具）并牺牲 plan 精度 |
| **D（WifiLock + low latency）** | **已落地**（`WifiLink.kt` + `ServerService` + manifest + 单测）。实测手机**当前没有任何 Wi-Fi 锁**、low-latency watchlist 为空；同一条链路 ping 0.2 s 间隔 **avg 26.8–45 ms / max 118–126 ms**，0.05 s 间隔 avg 7.0–8.8 ms ⇒ 省电唤醒一次就要一个帧预算 |
| **C（preview 流水线）** | **已落地**（`model_state.py`：preview 的帧不再等自己的回包）。帧线程原来被 hold 阻塞到 46/55 ms，正好压在相机 50 ms 上 ⇒ modeld 掉相机帧；现在自有开销回到 warp+pack（~5 ms），plan 仍是「新一帧的那份答复」，而手机的 queue 不再空转 |
| 上游 PR | 按用户「先不 PR」：**不动上游**，两个提交只在本 fork 的 `cn` 上 |

**没有做的事**（后面 §5）：app 侧跨帧双缓冲（control 路径的那份流水线，`host.lock` + 单套 staging 要拆双份）、上行帧的**时间维**压缩。

## 1. B 的前提：73.8 KB 是 `output_nbytes`，不是响应

上一轮我写「响应里 18452 个 float32 = 73.8 KB 是裸发的」——**那是整份 output 的大小**。protocol v3 的注释与
`jetlink/spec.py` 写得很清楚：`hidden_state` 留在服务器（`ModelState` 自己喂回去），响应只带 `outputs` 减掉它。

本机（不是记忆）从**跑着的大模型自己的 spec** 算出来：

```
$ python3 -c "import json;from jetlink.spec import ModelSpec;d=json.load(open('/data/params/d/JetlinkSpec'));s=ModelSpec.from_dict(d);print(s.hidden_range, s.output_nelem, s.reply_nelem, s.infer_resp_nbytes)"
(2066, 18450) 18452 2068 8292
```

- `sha256 404a18cfd86d2963…`（= 日志里 `loaded 404a18cfd86d2963`、`/data/media/0/models/jetlink/404a18cfd86d2963.onnx`）
- `hidden_state = slice(2066, 18450)` ⇒ 响应 2068 float = **8,292 B + 32 B 头 = 8,324 B/帧**
- 客户端对不上会直接死链（`inference response is N bytes, expected 8324`），链路是通的 ⇒ 手机上真的就是 8 KB
- `SEND_RAW_PRED`（`Flag.WANT_HIDDEN`，73,860 B）在手机上**没开**：modeld 的 `/proc/<pid>/environ` 里没有这个变量

算到链路时间里：

| 方向 | 字节/帧 | @10 MB/s |
| --- | --- | --- |
| 上行（warp，lossless packed） | 183 KB | ~18 ms |
| 下行（响应） | **8.3 KB** | ~0.8 ms |

所以上一轮那 24.8 ms 的「消失的往返」（`wait 50.5 − server total 25.7`）几乎全是**上行 + 电台唤醒**，
下行只占 1 ms。B 若按 f16 落地，省的是这 1 ms 的一半。

**结论**：字节的杠杆在上行（已 lossless 2.1x，见下），不在响应。真正的杠杆是 D（唤醒）与 C（重叠）。

## 2. D：Wi-Fi 锁（已落地）

### 证据（本机实测）

```
$ adb shell dumpsys wifi | grep -A6 WifiLockManager
Dump of WifiLockManager
Locks acquired: 0 full high perf, 70 full low latency
Locks released: 0 full high perf, 70 full low latency
Locks held:                      ← 空
Low-latency uid watchlist:       ← 空
```

⇒ **app 与系统都没有为这条链路持锁**（Kotlin 里从来只有 `PARTIAL_WAKE_LOCK`，CPU 域，与电台省电无关）。

```
$ ping -i 0.2 -c 15 192.168.10.65      → rtt min/avg/max = 4.4/45.0/126.5 ms
$ ping -i 0.05 -c 30 192.168.10.65     → rtt min/avg/max = 4.2/8.8/44.9 ms
```

⇒ 典型的 802.11 省电（PSM）唤醒惩罚：一次唤醒 ~40 ms，就是**整个 20 Hz 帧预算**。

### 改动

| 文件 | 改动 |
| --- | --- |
| `android/.../server/WifiLink.kt`（新） | `WifiManager.WifiLock`，`WIFI_MODE_FULL_LOW_LATENCY`（API 29，本机 `SupportedFeatures` 里确有 `WIFI_FEATURE_LOW_LATENCY`），栈不收时回落到 `WIFI_MODE_FULL_HIGH_PERF`；`wanted(medium)` 纯函数：**只有非 USB 链路才持锁** |
| `android/.../server/ServerService.kt` | 与 CPU wake lock 同一处、同一个 `snapshot.connected`：`wifiLink.hold(connected, snapshot.medium?.name)`；`onDestroy` 释放 |
| `AndroidManifest.xml` | `ACCESS_WIFI_STATE` |
| `app/src/test/.../WifiLinkTest.kt`（新） | usb/usb2/usb3/usb1 不持锁；wifi/wifi24/tcp 持锁；`null`/空 不持锁 |

不持锁的两种情况：**USB 链路**（帧走线，电台空闲，不该花这份电）与**只是在听 presence**（每秒一个包）。

### 怎么复验

1. Wi-Fi 链路 + 行车预览跑起来，手机上 `adb shell dumpsys wifi | grep -A4 "WifiLockManager"` ⇒ 应见
   `Locks held: <uid=… type=low_latency tag=jetlink:serving>`；
2. 同时从 comma `ping -i 0.2` 手机 ⇒ avg 应从 ~45 ms 掉到 ~10 ms 以内；
3. 帧日志 `wait` 一项应同步下降（§3 的复验清单）。

## 3. C：preview 的帧循环不再等自己的回包（已落地）

### 现场（上一轮的账）

```
一帧 = warp 2.5 + data 0.6 + send 1.9 + wait 50.5 = 55.5 ms   ← 相机周期 50 ms
其中手机自报 gpu 25.1 / queue 0.4 / total 25.7 ms，396/637 帧 held
```

`end()` 里 `infer_end(seq, hold=…)` 会**阻塞 modeld 的帧线程**到 `WIFI_HOLD_FRAME` 55 ms：
等来的答复即使到了，也已经在相机 50 ms 之外 ⇒ modeld 掉相机帧（`dropped 0.87–1.01 %`）；
而它 publish 的本来就是「上一份答复」——**等，没有任何收益**。

### 改动（`jetlink/openpilot/model_state.py`）

| 位置 | 改动 |
| --- | --- |
| `pipeline` 属性（新） | `self._pipeline and self.preview`：**只有 preview 会流水**，且是**从 `preview` 派生**——`joining` 在「有东西能接管」时把 `preview` 清掉（`PreviewEndsTest`），帧循环立刻回到「等自己的回包」，方向盘这条路径一字未动 |
| `end()` | 有答复在手时**不等**：publish `client.last_output`（`prepare()` 的 `drain()` 刚读进来的最新一份），自己的答复由后面的帧读走 |
| `prepare()` | `drain()` 返回 >0（host 答复过）时刷新 `_last_answer`：**静默规则的时钟是「上一份答复」**，不是「这一帧自己的回包」——否则每一帧都会被读成静默 |
| `_note_pipeline()`（新） | preview 的判罚只留静默（`PREVIEW_SILENCE` 5 s），原来嵌在 `_note_hold` 里的那份逻辑抽出来共用 |
| `Trips.pipelined`（新） | 流水帧单独计数，**不算 held**（它不是「迟到」，是这套循环的形状）；`joining` 的 leave 摘要与 `Session.swift` 的日志行同步多一项 `N pipelined` |

### 期望（这次为什么能到 20 fps）

| 量 | 之前（preview，Wi-Fi） | 现在 |
| --- | --- | --- |
| `end()` 等待 | 55 ms（阻塞帧线程） | ~0 |
| 帧线程自有开销 | warp+pack+**等待** ≈ 55 ms | warp 2.5 + pack 2.1 + 解析 ≈ 5 ms |
| 相机帧 | 掉 0.87–1.01%（`_frame_drop_ratio` 越线） | 不掉（不再越过 50 ms） |
| 手机的 queue | 0.4 ms（加速器空转） | 一直在算（上一帧在算时，下一帧已在途） |
| publish 的 plan | 上一份答复（等超时之后） | 上一份答复（本来就是这样）——**延迟没变差** |

### 测试

```
$ python3 -m unittest discover -s tests/openpilot -t . -p 'test_model_state.py'
Ran 55 tests … OK
$ PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests -q -p no:cacheprovider
40 failed, 1045 passed, 30 skipped, 4 errors      # 与改动前的 pristine 树逐条一致（都是本机环境：pytest 插件/厂商目录）
```

新增/改写的用例都在 `tests/openpilot/test_model_state.py`：

- `TestAPipelinedPreview.test_no_frame_after_the_first_waits_for_its_own_reply`（只有第一帧等它自己的预算）
- `…test_the_newest_answer_is_what_a_pipelined_frame_publishes`
- `…test_a_link_that_will_not_take_a_frame_is_not_waited_for_either`
- `…test_the_wheel_never_pipelines` / `…test_a_driven_away_preview_waits_for_its_own_reply_again`
- `…test_the_silence_clock_is_the_hosts_answers_not_this_frames_reply`（用一支**步进假时钟**把 5 s 的静默规则
  从「假件跑得太快」里救出来：迟但一直答的 host 永不交还，真不答的 16 帧内交还）
- `TestAPreview.test_a_preview_that_still_waits_holds_its_frames`（`pipeline=False` 时行为回到从前）
- `FakeClient.drain()` 现在也像真客户端那样把「答了但没有输出」记成 `last_failed`（`_take_reply` + `tolerate_failed`）

### 复验清单（真车，一次 Wi-Fi 预览就够）

1. `IsOnroadPreview` 关→开（让 manager 重拉 modeld）⇒ `large model joined mid-drive, modelV2.big is now true`；
2. `grep 'jetlink: frame' swaglog` ⇒ `wait` 应接近 **0.0 ms**，`held` 注释应变成 `, pipelined`，
   帧周期 p50 应贴着 50 ms（20 fps），不再有 `dropped 0.xx % of camera frames behind the large model`；
3. 手机侧 `server gpu/queue/total`：`queue` 应不再恒为 0.4 ms；
4. 拔掉 Wi-Fi 前看一次 `leave` 摘要：`N pipelined, 0 held`。

## 4. 顺带记下的

- 无线上 adb 现在**真的持久**了：`/home/comma/.android → /data/ai/adb/.android`（unit 开机恢复），
  本轮重新配对（`38153` / `721497` → connect 落到 `41801`）后 `adbkey` md5 未变 ⇒ 下次重启不用再配。
- `comma` 的 `/tmp` 是 150 MB tmpfs，上一轮压测把它写满过；本轮临时文件都写在 `/tmp` 以外，且已确认
  `/data/openpilot/jetlink_repo` 里没有残留的 `__pycache__` 之外的产物。

## 5. 没做的（下一层，按收益排）

| # | 做法 | 预期 | 代价 |
| --- | --- | --- | --- |
| 1 | **app 侧跨帧双缓冲**：算 N 时收/stage N+1（`Session.serveForever` 单线程 + `host.lock` + 单套 staging 要拆双份） | Wi-Fi 再省一次上行与解压的重叠（~5–12 ms） | 中：协议已允许多帧在飞（回包带 frameID），要动 Android/Swift 侧 |
| 2 | **上行帧的时间维压缩**：MED 是空间预测；让 lossless 的 GPU 图同时读上一帧做时间维残差（服务器侧留上一帧即可） | 183 KB → 可能 100 KB 量级（@10 MB/s 省 ~8 ms） | 中高：动 tinygrad 图 + 两边 codec |
| 3 | 换 AP/信道、关掉手机热点自扰、行车用 USB | 现场就能拿（上一轮 A） | 零 |
| 4 | B 的 f16 响应（若将来真有 2.4 GHz / USB2 手机） | <1% | 低但收益也低，**不建议** |

**上游 PR**：按用户「等后续都处理完毕再决定」，本轮不推上游；两个提交只在 `FOREVERZAX1988/jetlink` 的 `cn` 上。

## 6. 还没验的（要编译 / 要真车）

- D 的 Kotlin 与 C 里那行 Swift 日志**本机没有编译器**（这台 comma 上没有 swift / kotlinc / jdk），
  由 CI 验：`ci.yml` 的 `swift test --package-path JetlinkKit` 与
  `./gradlew --no-daemon :app:testDebugUnitTest :app:assembleRelease`。
  已推到 fork（`FOREVERZAX1988/jetlink` `cn`，**不是**上游），第一轮的结果：
  - `2063229` → **Android app FAILED**：`WifiLinkTest.aMediumNobodyNamedGetsNone`
    抓到 D 自己的一个错（`""` 不是 null、也不以 `usb` 开头 ⇒ 凭一个没人给的名字持了锁；
    锁按猜持就是电按猜花）。同时 Kotlin 编译器报了 `WIFI_MODE_FULL_HIGH_PERF` 在 API 37 已废弃
    （正是我们主用的 LOW_LATENCY 把它顶掉的），两条都在 `79dd730` 修掉。
  - `79dd730` → **CI 全绿**（17 个 job：Android app 78 个单测 + assembleRelease、
    Swift build and tests、swift-format、Python lint/tests、installer、cn prerelease）。
  - 顺带：`60ed27b`（上一轮那个提交）的 macOS 测试挂过一次，是
    status page 那套（PageFeedTests / PageAuthTests / PageServerTests）在 runner 上的抖动，
    本轮同 job 通过 ⇒ 与本 fork 的改动无关。
- C 在本机跑过：`tests/openpilot/test_model_state.py` 55 个用例 OK，全量 pytest 与 pristine 树逐条一致；
  真车复验清单见 §3。
- 结构性慢于 20 Hz 的 host（例如 60 ms/帧的手机）：流水线下 in-flight 会累积，最终由 client 的
  3 s deadline 触发一次 demote+retry（旧行为是每帧 held、掉相机帧、再由 drop 规则交还）——
  两条路都交还，故按设计接受，但真车上值得留意 `no answer to N frames in 3.0s` 与
  `frame N (seq M) was never answered` 这两行。
