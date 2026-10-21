# Safe Mode 里有一个本树不存在的键：`NNFFMode`（2026-10-21，offroad 实机发现）

## 现象

第 17 条（Safe Mode 端到端）在**实机**上跑通反证路径时暴露：`SAFE_MODE_MANAGED_KEYS`
里的 `NNFFMode` 在 `params_keys.h` 里**没有声明**，本树的神经网络前馈开关叫
`NeuralNetworkLateralControl`（`params_keys.h:267`）。

```
>>> Params().get("NNFFMode")
UnknownKeyName: b'NNFFMode'
```

`apply_safe_mode()` 里 `_get()` 把异常吞成 `None`（"不认识的键 = 没设过"），所以：

- 不崩溃、不报错；
- `SAFE_MODE_FIXED_VALUES["NNFFMode"] = "0"` 那一行**什么也没做**——Safe Mode 声称会
  关掉神经前馈，实际从来没关过；
- 备份里也永远没有这一项。

**为什么单测没抓到**：`FakeParams` 接受任何喂给它的键（`KEY_TYPES` 表是自己手写的），
所以「键是否真的注册」这件事在纯单测里不可见。这正是模块 docstring 里那句
「A list copied wholesale from another fork would name keys that are not registered
here」警告的情形，只是它自己在犯。

## 改法

1. `safe_mode.py`：`NNFFMode` → `NeuralNetworkLateralControl`（MANAGED 与 FIXED 两处）。
   `_coerce` 按注册类型写 BOOL，`put(False)` 存 `"0"`，语义与原意一致。
2. `tests/test_safe_mode.py`：
   - 用例里当样本的那个键同步改名，字面量 `"2"` → `"1"`（BOOL 只有 0/1）；
   - `KEY_TYPES` 对应项改 `BOOL`；
   - 新增 `TestKeysAreRegistered`（4 条）：
     - `params_keys.h` 可达性自检；
     - **Safe Mode 点到的每个键（managed ∪ remove ∪ fixed）都必须在 params_keys.h 里声明**；
     - `SAFE_MODE_FIXED_VALUES ⊆ SAFE_MODE_MANAGED_KEYS`（否则是死代码）；
     - 名字钉死回归：managed 里必须有 `NeuralNetworkLateralControl`、不许有 `NNFFMode`。
3. 反证护栏会红：把 `"NNFFMode"` 塞回 managed 列表 → `TestKeysAreRegistered` FAILED
   （点名 `NNFFMode`），撤回 → OK。53 tests OK，ruff 干净。

## 实机复验（真 Params，不是 mock）

修好后先在**新进程**里跑（避开 19:51 之前已经加载旧模块的服务）：

```
original: False
armed   : True
apply changed: True | backup entry: {'present': True, 'value': '1'}
forced  : False      # 真的被 Safe Mode 关掉了
restored: True       # 退出后回到用户值
```

再把服务重启（`sudo systemctl restart comma`，19:51）后**走 HTTP 接口**端到端复跑：

```
enter   : True
forced  : False | backup: {'present': True, 'value': '1'}
exit    : False
restored: True
final   : False | SafeMode: None
```

反证对照（修复前、旧进程）：同样步骤 `forced: True`、备份里没有该键 —— 一行代码在
屏幕上完全看不出差别，这也是它值得一条护栏的原因。

## 同一次 offroad 顺手记下的三条事实

1. **round 14 的重启验收（todos 第 16 条）**：19:45 重启后 manager 与 carrot_server
   都映射到 `libparams_c-1792575250-2907816.so`（重建产物，不再是 `(deleted)` 的旧
   inode）。同一台机上 `/api/safe_mode` **重启前 404、重启后 200**——这比「键表 +1」
   更能说明「跑的是旧代码」：路由是代码，不是数据。`/api/settings` 从 307494 → 321480
   字节；`CarrotEnabled` 的 `tuningLevel=1 settingsTier=0` 在目录里可见；天气六行在
   Cruise 页（`carrot_tuning_items.py:74-95`），`carrot_tuning_render_smoke.py`
   21/21 通过。
2. **manager 启动时会把所有有声明默认值的键写一遍**（`manager.py` 的 "set unset params
   to their default value"）。所以 Safe Mode 的备份在重启后看到 23/23 都是
   `present: true`（连 `SteerRatio` 都有 `"0.0"`），restore 又把 `"0.0"` 写回文件——
   那不是 Safe Mode 造出来的值，是开机就已经被物化的。对账要看**进 Safe Mode 那一刻**
   的备份，不是看更早的快照。
3. **`LateralJerkTorqueController` 与 `NeuralNetworkLateralControl` 同时为真时，
   `interfaces._cleanup_unsupported_params` 会把两个都置 False**（既有行为）。第一次
   做 A/B 时被这条坑到：arm `NNLC=True` 后几秒自己变回 False。要在实机上验 Safe Mode
   必须先把 jerk 控制器关掉，否则分不清是谁清的。

## 仍未闭合

- **第 18 条（天气）**：`weather_loop()` 每 30 s 一次，但 `read_position()` 没定位就
  直接 return——offroad 无 GPS fix 时 `/api/health` 的
  `weather: {"state": "clear", "latitude": null, "longitude": null}` 就是「循环在跑、
  但没有坐标所以没请求」。要验 `clear/rain/...` 之间真的切换，只能等一次带定位的路试。
