# 上游 test 第 4 轮移植（2026-10-21）：817f4a78c2..4630b96a77

上游 `mouxangithub/openpilot` `test` 又推进了 78 个我们还没有的提交，其中
**上一次审计（817f4a78c2）之后的 20 个**是本轮对象。这台机器上的对照是
`sync/upstream-1019` @ `985554f60c`。

## 已落地（本轮 7 个提交 + 1 个修复）

| 上游 | 本地 | 内容 | 门控 |
|---|---|---|---|
| d924d11b9b | e91a2ae78c | 邻车道静止车检测（Track 侧记账 + 检测函数） | 无消费方，纯记账 |
| c3ab2803e5 | 5f7c828a0b | 停车释放迟滞 + 负目标蠕行守卫 | StoppingReleaseHysteresisEnabled / NegativeTargetCreepGuardEnabled = 0 |
| ff32ddccf8 | 07e7d8f2c7 | 视觉居中曲率修正 | LaneCenteringEnabled = 0 |
| 265c29a27d | a8479ebdb9 | 弯道速度自学习（贝叶斯舒适横向加速度） | CscCurvatureLearningEnabled = 0 |
| 045e473a33 | a1a8260a31 | 不确定度 panic 门 / 重复前车守卫 / 模型前车轨迹 | 三个键 = 0 |
| da20eaaab4 | 5f7c4e8301 | 速度相关的跟车时距曲线 | LongitudinalFollowingProfileEnabled = 0 |
| 725bfb210d | 7795423183 | 天气条件化偏移（跟车距离/加速/横向） | WeatherOffsetsEnabled = 0 |
| （修 045e） | b53a1e2dcc | LeadForecast 包装层转发 process_lead 的关键字参数 | — |

外加 `02951bbf8c`（ruff W292）。

统一做法：所有门控读走 `sunnypilot/common/param_read.py`，所以**库没重建也不炸**
（`UnknownKeyName` 回落默认值），这正是上游 2d9c586376 的意图；我们之前已把
`param_read.py` 单独先搬（eafa58890d），本轮直接把调用点写成 `param_read`。

### 本轮抓到的真 bug

`045e473a33` 之后 MPC 用新签名调 `process_lead(lead, lead_index=..., model_lead=..., ...)`，
而本树 `LeadForecast` 用一个只收 `lead` 的包装替换了 `mpc.process_lead` →
**第一帧有前车就 TypeError**。纯逻辑单测全绿也发现不了，是闭环测试
`test_constant_curve_recovers_like_stock_speed_cap` 逼出来的。已修（b53a1e2dcc）。

## libparams_c.so

13 个新键已进 `common/params_keys.h`，用钉住 `-O0` 的单目标重建通过：

```
scons -j1 openpilot/common/libparams_c.so      # 261 MB 峰值，未触发 LMK
strings openpilot/common/libparams_c.so | grep -x <key>   # 13/13 OK
```

运行中的进程仍是启动时加载的旧 `.so`；因为所有新键默认 `0` 且读取容错，
不重启也没有行为变化。

## 验证

- `openpilot/selfdrive/controls/lib/tests` + SCC + lead_forecast：**301 passed, 1 skipped**
- SCC 里剩下的 1 failed + 1 error 是既有的 `carStateSP` 夹具缺口
  （stash 前后一致，与本轮改动无关）
- `openpilot/sunnypilot/carrot`：594 passed / 6 skipped / 41 error + 15 collection error，
  **全部是环境缺模块**（`cereal`/`yaml`），且本轮 27 个改动文件里 carrot 目录 0 命中
- ruff：仅剩 1 条既有的 F401（`sunnypilot/.../longitudinal_planner.py:36`，改动前就在）

## 还没搬的 12 条（已写进登记表 items，`12/12 still unported as recorded`）

**todo（独立可搬）**
- 25112d67f8 modes 纵向量模式状态机骨架
- a30b14cdab StarPilot 守卫（params / comm / 陈旧告警）
- 4630b96a77 模型体积台账（picker 显示本地已下载体积）
- 93b695da88 雷达点叠加档位（carrot ShowRadarInfo 0-3 档；本树完全没有这个键）

**todo-after（有前置）**
- 7fd88d270b + aab6ed90f8 进程 watchdog（新增 C++ 目标）
- 5ee2c9f618 Safe Mode 参数元数据（改 params.cc）
- dbe9c7c52c Safe Mode / SLC 舒适松绑（依赖 5ee2c9f618）
- d4136d1df0 视觉限速接进 resolver（依赖 d81eec5899）

**eval（体积/需驾驶者拍板）**
- d81eec5899 视觉限速 daemon（2883 行 + 22MB onnx）
- 63a6f3211b NNFF 横向神经网络前馈（127 文件，125 个车型模型 JSON）

**ui/settings**
- 0ba6c81d04 大 UI 里补 Rear Camera 一节、去掉重复 SLA 按钮、补中文翻译
  （参数本机已有，缺的只是屏上入口）

## Macan 口径

不支持的项一律「保留实现、默认关、UI 灰显不可点」：本轮 7 个提交全部默认 0，
没有任何一条会改变 Macan 的手感或加减速。等下一轮把 UI 入口补齐时，按同一口径
在 Developer / CarrotTuning 页给出灰显开关。
