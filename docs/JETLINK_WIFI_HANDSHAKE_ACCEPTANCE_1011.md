# JetLink Wi-Fi 握手 —— 设备验收（2026-10-11）

> 设备：C3（comma three）｜ 车辆：Porsche Macan ｜ 分支：openpilot `sp-macanlong-test`，jetlink `cn`
> 验收目标：App 的「链路：连接中」**只在 comma 真的接在本机热点、并被本机应答时**显示；
> 并且**不再误报 `Jetlink unavailable`**。本次验收把这两件事在真机上跑通并留档。

## 0. 结论速览

| 项 | 结果 |
|----|------|
| comma 侧通告确实带网关 | ✅ `{"jetlink":"presence","v":1,"id":"e3970911","gw":"127.0.0.1"}` |
| 网关处有 app 应答 → 握手 | ✅ `handshake True` |
| 没人应答 / 不在 Wi-Fi | ✅ `False`（不发也不认） |
| 通告循环在跑 | ✅ jetlinkd 持 UDP socket `0.0.0.0:43501` |
| `Offroad_JetlinkUnavailable` | ✅ 已清空（重启后未再出现） |
| `jetlink_adapter.reason()` | ✅ `None` |
| 手机热点场景 | ⏳ 需手机装新 APK 并开热点复验（见 §5） |
| iOS / macOS 应答端 | ⏳ 只在 CI 编译+测试过，要真机生效需各自出包 |

## 1. 改了什么（jetlink `cn`，openpilot 以指针跟随）

| commit | 内容 |
|--------|------|
| `8c92e5c` | comma 在 Wi-Fi 上向**它拨的网关**每秒单播一次 presence 通告；Android 端按「有没有 comma 应答」判「连接中」，不再只看开关 |
| `48a8756` | Wi-Fi 模式的 status 记录**不再带 gadget 的残留错误**（`error: gadget torn down`）；`status.unavailable` 收 mode 参数，读不到实时记录时也不误报 |
| `19f2e9b` | 通告带 `gw`：app 只在**自己是那个网关**时才应答、「连接中」才成立；comma 接了别的热点则显示「等待 Comma 接入本热点」；iOS / macOS 补上同一监听端（`JetlinkKit.PresenceMonitor`） |
| `fd0e3e9` | 日志措辞：握手边**由真变假**时报「它应答过的那个网关」，不再报「这一步所在的网关」（换网时后者是新网关，会误导） |

设计要点（`docs/link-protocol.md`、`jetlink/comma/wifi.py`）：
- 通告**只发单播到默认网关**。设计前提是「我拨的网关就是热点」，等于信任你输进 comma 的热点密码；
- 因此**从不广播**，同网不同 AP 的接法从一开始就不在支持范围（见 §4）。

## 2. 设备侧部署——「一直报 Jetlink unavailable」的真正尾巴

之前只把**代码**推上去了，但设备上跑的 jetlinkd 还是 **09:54 启动的旧进程**，
而 `wifi.py` 是 **10:28** 才写进磁盘的 ⇒ 设备一直在跑修复前的逻辑。处理：

- `SIGTERM` 掉旧 owner（manager 自动重启，新 pid **362707 @ 11:13:30**，加载新码；操作时 ignition=false、offroad，安全）。
- 清掉陈旧残留 `/dev/shm/jetlink-gadget`、`jetlink-net`、`jetlink-link`（里面就是那句 `error: gadget torn down`）。
- 结果（现已稳定）：
  - `/dev/shm/jetlink/status.json` → `"error": null, "net": null`（重启前 `net` 还带着那句残留）
  - `jetlink_adapter.reason()` → **None**（hardwared 就是拿它拉 `Offroad_JetlinkUnavailable`）
  - Params `Offroad_JetlinkUnavailable` → **已清空** ⇒ **不再报 Jetlink unavailable**
  - `JetlinkLink = 3`（wifi 模式）

> 教训：**代码推上去 ≠ 设备跑的是新码**。验收前先确认 jetlinkd 的启动时间晚于改动落盘时间，
> 再清 `/dev/shm` 的陈旧残留，否则会拿旧逻辑的现象当「修不好」。

## 3. 握手端到端验证（用设备上正在跑的这套码）

写了个一次性本地探针（跑完已删），直接调用设备上的 `jetlink.comma.wifi.Presence`：

- 通告确实带网关：`{"jetlink":"presence","v":1,"id":"e3970911","gw":"127.0.0.1"}`
- 网关处有 app 应答 → **handshake True**
- 没人应答 → **False**；无网关（不在 Wi-Fi）→ **False**（不发也不认）
- jetlinkd 进程持有一个 UDP socket（`0.0.0.0:43501`，即 Presence 的那个 socket）→ Wi-Fi 下通告循环确实在跑

## 4. 现场问题：comma 和手机在同一无线下，手机不是 AP

当前设备在 `Zzz-5G`（家用 5G，IP `192.168.10.79`，网关 `192.168.10.251`）——
**手机是这张网的客户端，不是 AP**。

- 通告是**单播到网关、从不广播**（设计如此：只信「我拨的网关就是热点」这一条），
  所以这种接法手机根本收不到通告 → 不会应答 → 新 APK 显示「等待 Comma 接入本热点」，
  **而不是**「连接中」。
- 之前显示「连接中」纯粹是旧 APK 只看开关（`StatusState.wifiLink`）。
- 结论不变：**这种接法点火后 JetLink 不能工作**（comma 拨 `192.168.10.251:5599`，那儿没人监听），
  只有**手机自己当热点**才通。

## 5. 未完成 / 下一步

- **手机端**：装新 APK `cn-19f2e9b` 及以后（https://github.com/FOREVERZAX1988/jetlink/releases ），
  否则手机端还是旧显示逻辑；要真正验证「手机热点」场景，得让手机开热点把 comma 接进去，
  再看两端是否 `Here / 连接中`。
- **iOS / Mac**：应答端只在 CI 里编过/测过，要真机生效得各自出包（iOS 走 TestFlight，见 `docs/publishing.md`）。
- **非同一 AP** 的接法不在支持范围，别拿它验收。

## 6. 下次上车复验步骤

1. 手机开热点（2.4 GHz 会告警，5 GHz 更稳），comma 连上该热点（Settings → Jetlink → Wi-Fi，填该热点密码）。
2. App 打开 Wi-Fi 链路开关 ⇒ 状态应到「连接中 / Here」（说明收到了 comma 的应答）。
3. 把 comma 切到**另一张** Wi-Fi（如家里的 `Zzz-5G`）⇒ App 应显示「等待 Comma 接入本热点」，**不得**显示「连接中」。
4. 手机端关闭 App（或关 Wi-Fi 链路开关）⇒ comma 侧日志应出现
   `jetlink: the Jetlink app stopped answering on <那个热点的网关>`（报的是**它应答过的**网关）。
5. 确认无 `Jetlink unavailable` 告警：`Params` 里 `Offroad_JetlinkUnavailable` 为空。
