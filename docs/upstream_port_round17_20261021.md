# 上游搬运 第 17 轮（2026-10-21）

基线 `sync/upstream-1019`，起点 `5034cefd01`，终点 **`33c2cdd8c3`**。
`git fetch upstream test` 后上游 tip 从 round 16 记录的 `1b36f1ad36` 前进到 **`5c2498a30e`**，
即新增 2 条：`d52602e6e6`、`5c2498a30e`。登记表 phase 2 仍只剩 `0facf5cf71`（agnos 腾讯镜像，skip）。

## 1. 两条上游提交

### `5c2498a30e` controls: two presentation fixes —— 已搬

| 文件 | 做法 |
|---|---|
| `controls/lib/latcontrol_angle.py` | **原样 checkout**（本树该文件与基线逐字节一致，没有 fork 内容） |
| `controls/tests/test_angle_saturation.py` | 原样 checkout，3 例 / 8 subtests 全绿 |
| `selfdrived/events.py` | **手写补 +54 行**：本树该文件有 200+ 行 fork 内容，checkout 会覆盖掉 |
| `selfdrived/tests/test_steering_warning_delay.py` | checkout + 改一行 import |

语义：①大角度误差 + 车自身转角速率限幅 = 限幅在做功，不是饱和；tesla/hyundai 保持传 `False`
（那里限幅信号本身就是饱和信号，传真值会让检测永远 False）。②`steerTempUnavailable` 单帧抖动不再
闪一下警告：累计 120 ms 才**渲染**，健康 1 s 才清零；事件本身照旧进 `self.events`，状态机、
soft-disable 计时器、critical takeover 全部绕过延迟（11 例都锁住了）。

移植时踩到一处本树特有的坑：上游测试写 `from openpilot.cereal import car`，本树 `car` 结构体在
`opendbc`，这行**永不解析**——与 `5034cefd01` 修的是同一类。改 `from opendbc.car.structs import car`。

### `d52602e6e6` lead_forecast: run its own tests for the first time —— 早已覆盖

我们在 round 15（第 21 条 todo）就把这两个测试转成 unittest 了，且是上游的超集
（`test_forecast` 26 例 vs 上游 25 例）。本轮只登记，不取代码；实测 26 + 3 全绿。

## 2. 三个真 bug（跑出来的，不是看出来的）

### (a) `EVENTS[0]` 被测试当成「空闲 id」，在这里是 canError

`selfdrived/tests/test_state_machine.py` 的 `make_event()` 写 `EVENTS[0] = {}`。上游 0 号是
`none`（保留不用），**本树 log.capnp 没有 `none`：0 号就是 canError**。于是这个测试每跑一次，
就在进程内把 canError 的告警映射清空一次，后续任何依赖它的测试都拿不到 immediate-disable。
新搬的 `test_other_faults_remain_immediate` 正好踩中：单跑过、整目录跑挂（`[] is not true`）。
把假事件 id 改成 `max(EVENTS) + 1`。修完 `selfdrived/tests` 整目录 **52 passed + 74 subtests，0 failed**。

### (b) `test_nnff_integration` 不测试、还会改车

它 `put_bool("EnforceTorqueControl", True, block=True)` 然后什么都不恢复。两个后果：
①阻塞写在设备上挂死（见 c），整个 7 例套件 40 s+ 无输出；②`EnforceTorqueControl` 在本 fork
是**影响行车**的键（`_enforce_torque_lateral_control` → `configure_torque_tune`），被测试留在 1。
改成 `block=False` + `setUpClass/tearDownClass` 保存并还原：**7 passed in 0.41 s**。
（`/data/params/d/EnforceTorqueControl` 现在仍是 1，是历史测试写的；要不要保留由驾驶者决定，
已登记待办，本轮不动行车相关的值。）

### (c) params 锁被「死进程」持有 —— 整栈的阻塞写都在等它

`params.cc` 的 `FileLock` 是 `open(fn, O_CREAT, 0775)`，**没有 O_CLOEXEC**（上游同款，非本 fork 引入）。
于是任何进程在持有 flock 时 fork/exec 出的子进程都会继承这个描述符，锁的生命周期就跟到子进程身上。
现场证据：`/proc/locks` 里该锁 owner 是 **pid 1937286（已死）**，而 ui(×2 thread)、hardwared、
models.manager、mapd_manager、athenad、sunnylinkd(×2)、carrot_man 共 9 个线程排在
`locks_lock_inode_wait` 上；`locationd` 的 **fd 43 → /data/params/.lock**，fdinfo 明写
`lock: FLOCK ADVISORY WRITE 1937286 ...`——锁跟着这个继承来的 fd 活着。

后果是全局的：**任何 `block=True` 的参数写都会永久阻塞**。`test_alerts` 之前「挂死」就是这个
（锁释放后 0.7 s 跑完 4 例），`test_params_migration`、`test_nnff_integration`、
`sunnylinkd/athenad` 的参数写同理。这也解释了 todo 里那条「实时系统的 params 锁导致无限阻塞」的猜测。

处置：
1. `params.cc` 加 `O_CLOEXEC`（一行 + 注释），`libparams_c.so` 用钉住的 `-O1 -g0` 重建：
   **368.9 MB 峰值 / 2:30 / exit 0**（记录值 361 MB，一致，没有触发 LMK）。
2. 现场解锁：以 SIGTERM 结束 `locationd`（manager 会重启它），重启后它拿到干净句柄；
   随后阻塞写立即恢复正常（已验证：`put_bool(block=True)` 从永久挂起变为瞬时返回）。

## 3. 验证数字

| 套件 | 结果 |
|---|---|
| `pytest openpilot/selfdrive/controls/lib/tests` | **266 passed, 1 skipped**（含此前「只在 pytest 下才跑」的 FLM 两文件，6 passed） |
| `pytest openpilot/selfdrive/selfdrived/tests` | **52 passed + 74 subtests**（修 canError 前是 1 failed） |
| `pytest openpilot/common/tests` | **66 passed + 258 subtests** |
| lead_forecast `test_forecast` / `test_planner_hook` | **26 / 3 passed** |
| `test_nnff_integration` | **7 passed**（此前挂死） |
| `opendbc.car.volkswagen.tests.test_macan_mlb` | **43 passed** |
| `test_macan_radar_fusion` / `test_vcruise_pcm_set_speed` | **10 / 6 passed** |
| `pytest openpilot/sunnypilot/selfdrive/controls` | 936 passed，**8 failed —— 全部既有**（`git stash` 摘掉本轮改动后同样 8 failed） |
| `openpilot/selfdrive/controls/tests` | 2 个文件（`test_leads`、`test_following_distance`）会挂：它们真起 `card` 子进程，实时优先级被系统拒绝后等在那里，与本轮无关 |
| ruff | 本轮触碰 6 个 py 文件全绿 |

## 4. Macan 适配完好性（本轮实测）

`PORSCHE_MACAN_MK1`：brand=`volkswagen`、转向控制类型=`torque`、安全模型=`volkswagenMlb`、
横向整定类型=`torque`、`pcmCruise=True`、`mass=2031.0`、`wheelbase=2.81`。
`opendbc` 是 `opendbc_repo/opendbc` 的软链（不存在陈旧的第二份拷贝）；子模块指针干净、无 `+` 前缀。
Macan 相关三套件 43 + 10 + 6 全绿。

## 5. 下一轮

上游代码层依然没有未移植项（只剩 agnos skip）。待办全是驾驶者侧：
①`EnforceTorqueControl` 现值 1 是否保留；②重启后确认新 `libparams_c.so` 生效，且 `/proc/locks`
里该 inode 的 owner pid 必须**活着**（再出现死 pid 就说明又有一个继承来的 fd）；③原有路试项不变。
