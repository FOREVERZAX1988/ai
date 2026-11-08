# 子模块 pin / remote-tracking ref 核查（2026-10-02）

结论先行：**本机 submodule 没有"没对齐"的问题，不需要 fetch 修复**；
真正存在的是 `opendbc` pin 与 SP 代码树的**版本错位**（Toyota 专属，与 Macan 无关）。

---

## 1. panda：远端 ref 已经是新的，无需 fetch

| 项 | 值 | 核实方式 |
|---|---|---|
| 子模块 HEAD | `4643ee2c6 适配F4` | `git -C panda log --oneline -1 HEAD` |
| 本机 `origin/sp-macan-re` | `4643ee2c6` | `git -C panda log -1 origin/sp-macan-re` |
| 远端真实值 | `4643ee2c61ef8b6ced0b9d2d194d9f018e60681f` | `git -C panda ls-remote origin sp-macan-re`（实测 8s 内返回，网络正常） |

三处一致 → 所谓"ref 还是旧的 `7d703710a`"只是**旧提交仍留在本地对象库/分支历史里**，
不是 remote-tracking ref 落后。`7d703710a` 是更早的提交，仍被
`remotes/origin/macan-long-0916/0920/0925/0926`、`master-c3` 等分支包含（`git branch -a --contains`），
属正常历史。**结论：不用跑 `git -C panda fetch`，也不需要修。**

> 判定口径：`git submodule status` 里 panda 显示为 `4643ee2c61… panda (remotes/origin/sp-macan-re)`
> —— 括号里是 HEAD 所指向的 ref，只要它与 `ls-remote` 的哈希一致即为对齐。

## 2. opendbc：pin 与 SP 代码树错位（本次仿真唯一"非 Macan"红项）

* pin：`opendbc_repo` @ `b5ee1ecb7`（分支 `align/master-c3-0929`，即 `origin/sp-macan-re` 尖端）。
* SP 树里的 `openpilot/sunnypilot/selfdrive/car/tests/test_custom_cruise.py` 导入
  `from opendbc.car.toyota.carstate import get_virtual_cruise_button, VIRTUAL_CRUISE_BUTTONS`。
* 该 API 的引入提交 `6e9536c64 feat(toyota): let supported cars own cruise set speed`
  **已被 `0e65ba76e` revert**，而这两个提交都是当前 pin 的祖先 → pin 处该 API 不存在 → `ImportError`。
* 该用例来自 openpilot fork 的 Toyota TSS2 功能并入（`2a5457e8e7`），它期待的是 SP 上游 opendbc
  的对应基线，与本仓 pin（mouxan `master-c3` 线）不同步。

**当时的处置**（历史口径，2026-11-08 已被第 5 节推翻）：不为一个 Toyota 用例去动
opendbc pin（会波及全部车型 + Macan 纵向三处接口），在仿真入口显式记为 SKIP。
**事后修正**：「不动 pin」是对的，但「只能 SKIP」是错的 —— 可以直接在 fork opendbc
当前树上把 API 补齐，完全不碰 Macan/VW 路径。详见第 5 节。

## 3. 复核命令（一次跑完）

```bash
cd /data/openpilot
git submodule status
git -C panda ls-remote origin sp-macan-re          # 与 submodule status 的哈希比对
git -C opendbc_repo log --oneline -1
/usr/local/venv/bin/python -c "from opendbc.car.toyota.carstate import get_virtual_cruise_button" || echo "opendbc pin 缺该 SP API（预期）"
```

> 设备上不要用 `/usr/bin/python3` 判断依赖，那是系统 Python；运行环境是
> `/usr/local/venv/bin/python`。

---

## 4. 复核（2026-11-08，上游 129 提交合并后）

上文第 1、2 节的哈希是 2026-10-02 的历史快照，不是当前值；每轮上游合并子模块 pin 都会变。
本轮合并（`dc548d8f0`）后的实测：

| 项 | 当前值 |
|---|---|
| `opendbc_repo` | `4223e8a3`（`sp-macan-1029`：我方 Macan/VW 30 文件改动 + 上游 `8370c432` 纯历史合并） |
| `panda` | `948072db8e`（4 个固件产物随树携带，变砖红线通过） |
| `msgq_repo` | `3eeae59a77`（URL 改为 `zoompilot/msgq`，构建改用 nanobind） |

* **Toyota API 当时仍缺**（已于 2026-11-08 补齐，见第 5 节）：在 `4223e8a3` 上
  `from opendbc.car.toyota.carstate import get_virtual_cruise_button` 仍抛 `ImportError`
  → `test_custom_cruise` 的 SKIP 判定当时成立，与本次合并无关。
  `ai/tools/sim_test_macan.py` 的 `skip_reason()` 每轮动态探测、不写死哈希；
  API 补齐后该用例已自动恢复执行。
* **10 个子模块 pin 全部可从 `.gitmodules` 声明 URL 拉取**
  （`ai/tools/check_submodule_pins.py`，`PIN_EXIT=0`）。
  设备 `.79` 的 `msgq_repo` remote 曾仍指向旧的 `sunnypilot/msgq`，已对齐到
  `zoompilot/msgq`（保留 gh-proxy 前缀）并验证 fetch 成功。
* 设备 VW safety 测试需带 `SAFETY_NO_SANITIZERS=1`（AGNOS 工具链缺 UBSan runtime，
  失败发生在 `setUp` 加载 `libsafety.so`，非代码回归）。

---

## 5. 2026-11-08：Toyota 虚拟巡航 API 已补齐，`test_custom_cruise` 恢复执行

结论：**不动 opendbc pin、不动 Macan/VW 任何路径**，直接在 fork opendbc 当前树上补齐
被 revert 的 API。历史里 `99ef6474 feat(toyota): let supported cars own cruise set speed`
被 `a68ae2ff` revert；不能照搬，因为当前树与那个提交差 184 行，且 flags 位已被占用。

补齐清单（Toyota 专属，默认关闭）：
* `opendbc/car/toyota/carstate.py`：新增 `get_virtual_cruise_button`、
  `VIRTUAL_CRUISE_BUTTONS`、`TOYOTA_VIRTUAL_CRUISE_LONG_PRESS = 65`
  （与主仓 `openpilot/selfdrive/car/cruise.py` 同值）；`CarState` 记录按钮状态，
  在 `update()` 解析 `CLUTCH` 的两个位并生成按钮事件，`get_can_parsers()` 按需注册 `CLUTCH`。
* `opendbc/car/toyota/interface.py` + `opendbc/sunnypilot/car/toyota/values.py`：
  `VIRTUAL_CRUISE_SPEED_CAR`（Corolla/Prius TSS2）与
  `ToyotaFlagsSP.VIRTUAL_CRUISE_SPEED_AVAILABLE`。**flag 用 2048 而不是上游的 256** ——
  本分支 256 已是 `SP_BRAKE_ONSET`，照搬会别名冲突。
* `opendbc/sunnypilot/car/interfaces.py`：读 `ToyotaVirtualCruiseSpeed`（默认 0），
  仅在平台支持 + OP 纵向 + 用户显式开启时把 `CP_SP.pcmCruiseSpeed` 置 False；
  stock longitudinal 永远优先。
* `opendbc/dbc/generator/toyota/_toyota_2017.dbc`：`CLUTCH` 增加
  `CRUISE_RES`(bit5) / `CRUISE_SET`(bit4) 及注释。
* 主仓 `openpilot/common/params_keys.h`：登记 `ToyotaVirtualCruiseSpeed`（BOOL，默认 0），
  否则 `params_dict` 里永远没有该键、功能无法开启。
* 新增 `opendbc/sunnypilot/car/toyota/tests/test_virtual_cruise_speed.py`（9 项回归）。

**补齐 API 后暴露的真问题**：`test_custom_cruise` 从「整组 SKIP」变成 **12 个 FAIL**，
全部表现为 `v_cruise_kph` 冻结在 seed 值。根因不是 opendbc，而是 fork 的
`VCruiseHelperSP` 把 `pcmCruiseSpeed` 重定义为 `not icbm_latch.active`（每帧刷新），
而 SP 上游搬来的测试假设它是静态 `CarParamsSP.pcmCruiseSpeed=False`。
`icbm_latch` 未激活 → `pcm_cruise_speed=True` → `update_v_cruise()` 不调用
`update_button_timers()` → 按钮事件从不记录。
修法在 `test_custom_cruise.py` 的 `TestToyotaVirtualCruiseSpeed.setup_method()`：
用 `unittest.mock.patch` 停掉 `update_icbm_latch` 刷新并固定 `icbm_latch.active = True`，
隔离出真正的软件 PCM 增量路径，**不改任何实车巡航逻辑**。改后 `43 passed / 0 failed`
（原 12 红全部真跑通，含 route payload 的 CAN 位解析用例，间接验证了 DBC 位定义）。

`ai/tools/sim_test_macan.py` 的 `skip_reason()` 逻辑保持不变：动态 `_probe` 现在返回
`OK` → 不再 SKIP；保留它作为回归保护，若未来上游合并又把 API revert 掉，会自动
退回 SKIP 并打印原因，不会伪装成 Macan 代码回归。
