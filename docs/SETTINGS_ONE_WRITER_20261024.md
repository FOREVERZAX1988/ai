# 设置双端统一：一份存储 · 一个写入口 · 各自跟随

日期：2026-10-24 · 车机 `/data/openpilot` · 分支 `sync/upstream-1024`

## 为什么做这一轮

用户的原话是「不管在 comma 设备里打开这个设置还是网页端打开，修改的那一刻都应该同步到另一端」。
对照代码，两端的设置确实不是一套体系，而是三处各自为政：

1. **两个写入口。** 车机 UI 走 `Params.put_bool`（`ExperimentalMode` 还带风险弹窗与确认位）；
   网页面板 `sunnypilot/carrot/web_settings.py:apply_updates` 直接 `params.put` 裸写；
   伴侣 App 走 `server/features/params.py`，那条路**已经**经过 `mode_state_runtime`。
   于是同一个开关有三套规则。
2. **车机 UI 只在状态切换时刷新。** 各设置页把控件状态绑在
   `ui_state.add_offroad_transition_callback` / `engaged_transition` 上，控件构造时读一次参数。
   浏览器改完，车机要等到下次离车/接合才显示，中间两端显示不一致，而存储其实早已正确。
3. **`UnifiedParams` 的 JSON 侧是进程内副本。** 未注册到 `params_keys.h` 的 carrot 调参键走
   `nav_params.json`，`_nav_data` 只在构造时读一次盘，别的进程（网页面板的导航参数页、工具）
   改完它看不到。

## 落地内容

### 1. 能力判定收敛成一处（同时修掉「实验模式重启后总是关掉」）

`sunnypilot/common/mode_state.py` 新增 `longitudinal_capable(openpilot_longitudinal,
alpha_available, alpha_enabled)`：有 alpha 纵向就以 `AlphaLongitudinalEnabled` 为准，否则看
`openpilotLongitudinalControl`。

- `selfdrive/selfdrived/selfdrived.py` 的启动清理改成用它。**这就是重启丢实验模式的根因**：
  这一行原来只问 `CP.openpilotLongitudinalControl`，而本车走 alpha 纵向（`AlphaLongitudinalEnabled=1`），
  于是每次 selfdrived 启动都把 `ExperimentalMode` 删掉；同一时刻设置页却用 alpha 感知的判据把开关
  显示为可用 —— 开关能开、进程一重启就抹掉。
- `selfdrive/ui/ui_state.py` 的 `has_longitudinal_control` 改成同一个调用，两处不再各算各的。

### 2. 网页面板不再裸写「有规则的键」

`web_settings.apply_updates` 遇到 `ExperimentalMode` / `SafeMode` 时改走
`mode_state_runtime.set_experimental_mode(..., acknowledged=True)` 与 `safe_mode_runtime.set_safe_mode`，
被拒绝（Safe Mode 锁、路面状态不明、未确认）就计入 skipped 而不是写进去。

这条同时解释了另一个现象：网页端曾把 `ExperimentalMode=1` 裸写进去，确认位仍为 0，
`experimental_mode_requested()` 一直返回 False —— **开关是亮的，模式其实没生效**。现在两条路都写确认位。

顺带：面板的写入也记进 `param_changes.jsonl`（source `web_ui`），和伴侣 App 用同一份变更历史。

### 3. 车机控件跟随存储（2 Hz）

- `system/ui/sunnypilot/widgets/toggle.py`：`ToggleSP.sync()`，渲染时最多每 `SYNC_INTERVAL=0.5s`
  读一次自己的键。刚写入的值在 `PENDING_WRITE_TIMEOUT=1.0s` 内保持权威（Params 的写是异步的，
  写完立刻读会读到旧值），超时后以存储为准 —— 被拒的写必须显示出来，而不是被永久掩盖。
- 新增 `sync_param`：写由回调负责的开关（实验模式要先弹风险确认）只镜像这个键，不自己写。
- `option_control.py`：`OptionControlSP` 同样处理（`_stored_value()` 抽出构造时的读取逻辑）。
- `alpha_longitudinal_toggles.py`：`Alpha Longitudinal` / `Experimental Mode` 两个回调型开关接上
  `sync_param`；弹确认对话框期间 `set_sync_paused(True)`，避免存储里的旧值把开关在对话框背后翻回去。

### 4. `UnifiedParams` 跟随 JSON 文件

`config.py`：`get()` 里按 1 s 一次的节奏 stat `nav_params.json`，mtime 变了就重载，别的进程写的值
因此能被车机看到（未注册键的唯一存储就是它）。
`remove()` 只在 JSON 里确实有这个键时才重写文件 —— 以前任何一次清注册键都会把整个文件重排、
丢掉 `_comment`，让「只读」操作在 git 里看起来像改过文件。

### 5. 路面状态两半一起写

`system/manager/manager.py`：`IsOnroad` 和 `IsOffroad` 同时维护（`_mirror_onroad()`，
库表里没有这个键时静默跳过，绝不因此让 supervisor 挂掉）。
`mode_state` 要求路面状态「已知且不矛盾」，而全仓此前**没有任何地方写 `IsOnroad`**，
所以车一动起来，伴侣 App 和网页面板都改不了实验模式。

## 验证

```
python3 -m pytest openpilot/sunnypilot/common/tests openpilot/system/ui \
                 openpilot/sunnypilot/carrot/tests -q     # 1123 passed
```

新增测试：
- `sunnypilot/common/tests/test_mode_state.py`：`TestLongitudinalCapability`
- `sunnypilot/carrot/tests/test_carrot_web_settings.py`：`TestApplyUpdatesUsesTheOneWriter`
  （网页端开实验模式必须同时点亮确认位；路面状态不明/Safe Mode 锁 → skipped 不写入；关模式不动确认位）
- `system/ui/sunnypilot/widgets/tests/test_toggle_sync.py`：
  远端写入到达、自己的写在异步窗口内不被回滚、写被拒后以存储为准、暂停不跟随、只有 sync_param 只读不写

顺手修掉两个「靠测试污染才通过」的用例（`test_carrot_man.py` 里读 `Params._store` 的写法：
一个后端里根本没有这个属性，另一个后端下会把值写进车机的 `/data/params`）。
改用 `_MemorySystemParams` 注入，两个用例从此不依赖执行顺序、也不碰真机存储。

## 上车要看的

1. 设置里打开实验模式 → 重启 → 应保持开启（此前必被清掉）。
2. 浏览器面板改任意开关 → 车机设置页 0.5 s 内跟着变。
3. 车机改 → 浏览器刷新即见（面板本来就是按请求读实时值）。
4. 车动起来后，App/网页改实验模式不再被「路面状态不明」拒绝。

## 还没做的（下一轮）

- `multiple_button_item_sp`（`MultipleButtonActionSP`）还没接跟随，仍是构造时读一次。
- 未注册键仍留在 `nav_params.json`，没有并进 `params_keys.h`（并进去要重建 `libparams_c.so`，
  本机 `scons` 编 `params.cc` 会被 lowmemorykiller 杀掉，见 `carrot_web_push_20261021.md` 的同一结论）。
- 跟随是「各自轮询」，没有共享的版本号；跨进程通知（代际号/变更日志 token）能省掉这些读，
  但要新增注册键或新文件，留待与参数表重建一起做。
- `mode_state_runtime.set_experimental_mode(capable=...)` 这条**能力锁**目前没人传：
  伴侣 App / 网页端可以在没有 openpilot 纵向的车上下发 `ExperimentalMode=1`（写进去但不生效，
  下次 selfdrived 启动再清掉）。要接就得在服务端把 `CarParamsPersistent` 解出来喂给
  `longitudinal_capable()`；这条链依赖 cereal，本机（缺编译产物）测不了，所以先不动，
  记为下一轮 —— 方向上它只会更严，不会放开什么。
