# 仿真为什么要加「上车前一致性预检」——2026-10-10 sunnypilot Unavailable 复盘

## 1. 现象与两个根因

点火后 UI 报 **sunnypilot Unavailable / Waiting to start**（= `ALERT_STARTUP_PENDING`：UI 已 onroad 但收不到
`selfdriveState`，即 selfdrived 没起来）。`/data/community/crashes/` 显示上下电各崩两个进程：

| 进程 | 崩溃点 | 根因 |
|---|---|---|
| card | `interfaces.py:145 initialize_params` → `UnknownKeyName: b'ToyotaBrakeOnset'` | `libparams_c.so` 是 10-09 21:26 编的，而合并提交 `10a50b743d`（10-10 01:05）新增了参数键 → 编译好的 native 键表里没有这些键 |
| modeld | `make_split_input_queues` → `TypeError: 'NoneType' object is not reversible`（tinygrad `uop/ops.py`） | tinygrad 子模块 pin 被误 bump（`66ee3cfb4`），与模型 bundle 的 pkl 不匹配 |

修复：`811e6e9ded`（tinygrad 回退 `f6fc4e3f2` + `launch_chffrplus.sh::ensure_params_build` 在
`params_keys.h` 比 `.so` 新时重建）。

## 2. 为什么「每次仿真都测不出来」

因为我们说的「仿真」= **纯 Python 源码级** 用例（carcontroller/carstate/按键/巡航的 unittest，
`ai/tools/sim_test_macan*.py`，`boot_smoke_test.py` 的 import + AST 扫描）。它们：

- 用 `PYTHONPATH` 直接 import 源码，**从不加载编译产物** `libparams_c.so`，所以 .so 过期看不见；
- 不启动 manager/modeld，**从不反序列化模型 pkl**，所以 tinygrad pin 错位看不见；
- 断言的是「控制律/信号」语义，而这两个故障是**构建与 pin 的一致性故障**（环境态，不是源码态）。

一句话：**故障类别和仿真覆盖面正交**。要在仿真里挡住它，必须显式断言「跨产物一致性」，
或真的把模型/原生产物跑一遍。

## 3. 补的东西：`ai/tools/sim_preflight.py`

| 阶段 | 检查 | 对应根因 |
|---|---|---|
| A1 | `libparams_c.so` 存在且比 `params_keys.h` 新（与 `ensure_params_build` 同判据） | 根因 A |
| A2 | 编译好的 native lib 必须认识 `params_keys.h` 里**全部** 632 个键（`Params.check_key`） | 根因 A |
| A3 | 源码里 `Params.get/put("字面量")` 的键必须已登记（AST 扫描；小写字面量=dict/json 字段，列 WARN 跳过） | 根因 A（同类，提前抓） |
| B1 | 活动 bundle 的 driving pkl（含分片 manifest）/ native `modeld` 产物 / modeld 关键模块 import | 根因 B |
| B2 | `--model-load`：按 `modeld_v2._init_combined` 真实调用序列 `load_oob` → `metadata` → 建输入队列 | 根因 B（崩溃发生点） |
| C1/C2 | `--runtime`：关键进程存活、manager 单实例（fork 子进程按父进程识别，不拿 cmdline 计数）、本次启动后是否新崩溃 | 现场三链 |

已并入一键仿真：`python3 ai/tools/sim_test_macan.py`（boot smoke + 预检 + 6 组 unittest）。

### 设计取舍（别当 bug 看）

- **B2 默认不跑**：一个 175MB 的 pkl 反序列化峰值内存约 4× 体积，C3 只有 3.6GB 且无 swap。
  默认带内存护栏 SKIP，`--model-load [--force]` 时才在离车时跑。**不拿「可能把设备 OOM 打挂」换一条绿灯。**
- **WARN ≠ 放行**：`KNOWN_NONKEYS`（已知例外）与「疑似非键名字面量」都逐条打印出来，不静默吞。
- 预检**只读**：`Params.check_key` 不发写，不碰 panda，不改任何参数。

## 4. 预检当场抓到的东西

- **`MazdaTjaButton`（上游缺陷，同类故障）**：`openpilot/selfdrive/ui/sunnypilot/mici/layouts/steering.py:92/203`
  读写这个键，但**本仓与 `upstream/test` 的 `params_keys.h` 都没登记**（全仓仅这 2 处、无写入方）
  → Mazda 上走到这行即 `UnknownKeyName`。非本车（Toyota/Macan）路径，属上游修，已进 KNOWN_NONKEYS 并打 WARN。
- **一个 fork 子进程长期未改名**（PID 18930，挂 39min、state=S）→ 值得查是哪个托管进程卡在启动。

## 5. 仍然只能上车验的部分（诚实边界）

- native `modeld` 二进制本身（111B 只是个 wrapper，真正的运行期行为要跑起来才知道）；
- `selfdrived/card` 的 onroad 启动链（offroad 不起，C1 只能 SKIP）；
- 因此建议：上车后先 `python3 ai/tools/sim_preflight.py --runtime`（10 秒内出结论），
  再看 `/data/community/crashes/` 是否有「本次启动后」的新崩溃（C2 已自动比对 manager 启动时间）。
