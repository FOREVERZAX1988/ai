# libparams_c.so 单目标重建配方（LMK 安全路径）— 2026-10-21

## 为什么必须重建

`openpilot/common/params_keys.h` 是**编译期**键表，`keys` 是 header 里的
`inline static std::unordered_map`，被 `params.cc` 编进 `libparams_c.so`。Python 侧
`openpilot/common/params.py` 用 `ctypes.CDLL(_params_lib_path())` 加载的是**私有副本**：

```
/data/.cache/params_lib/libparams_c-<源文件 mtime>-<源文件 size>.so
```

（私有副本是 2026-10-17 SIGSEGV 事故后的保护：scons 原地重写 checkout 里的
`libparams_c.so`，内核会把新字节喂给已经 mmap 旧文件的进程，导致别的进程在自己的
`.so` 里崩。）结论：改了 `params_keys.h` 而没重建 `.so`，新键在**所有**进程里都不存在，
`Params().get("<新键>")` 抛 `UnknownKeyName`；`param_read.read_float()` 会兜底成默认值，
所以是「静默不生效」，不是「崩溃」。

实测判据（本次前后对比，非 mock）：

| .so | keys 数 | 表里有 CustomKp | check_key(CustomKp) |
|---|---|---|---|
| 旧（10-17 构建） | 670 | False | False |
| 新（本次重建） | 671 | True | True |

## scons 正面路径为什么不行

```
scons -j1 openpilot/common/libparams_c.so
  -> [CXX] openpilot/common/params.o
  -> scons: *** [openpilot/common/params.o] Error -9      # SIGKILL
```

dmesg：

```
lowmemorykiller: Killing 'clang++' (610695), adj 0,
                 cache 4848kB is below limit 6144kB for oom score 0
```

机器 3.6 GB RAM、offroad 空闲时 MemAvailable ≈ 1.9 GB；`params.cc` 用
`-O2 -g -mcpu=cortex-a57` 单进程峰值就能把这个余量吃穿，LMK 直接杀编译器。
（2026-10-21 实测峰值见下一节：`-O1 -g` 1.9 GB，同样会被 LMK 杀；只有 `-O0` 的 261 MB 稳。）

## 可行配方（实测通过）

取 scons 自己的命令行（`scons -n --verbose -j1 openpilot/common/params.o` 打印），
只把 `-O2` 换成 `-O1`（保留 `-g`，便于以后看栈）：

```bash
cd /data/openpilot
FLAGS="-std=c++1z -D__COMMA_HARDWARE__ -mcpu=cortex-a57 -g -fPIC -pipe -O1 \
 -Wunused -Werror -Wshadow -Wno-unknown-warning-option \
 -Wno-inconsistent-missing-override -Wno-c99-designator -Wno-reorder-init-list -Wno-vla-cxx-extension"
INC="... 直接把 scons -n --verbose 打印的 -I 列表整段搬过来 ..."
clang++ -o /tmp/params_o1.o -c $FLAGS $INC openpilot/common/params.cc
```

链接用 scons 的 LINK 行，**但把新目标文件放在 `libcommon.a` 之前**（先满足符号，
避免从归档里拉出旧的 `params.o`）：

```bash
clang++ -o /tmp/libparams_c.so.new -Wl,--as-needed -Wl,--no-undefined -shared \
 -Wl,-rpath=/usr/local/venv/lib/python3.12/site-packages/ffmpeg/install/lib \
 openpilot/common/params_c.os /tmp/params_o1.o \
 -Lopenpilot/common -Lmsgq_repo -Lopenpilot/selfdrive/pandad -Lrednose_repo/rednose/helpers \
 -L.../site-packages/{acados,capnproto,eigen,ffmpeg,json11,ncurses,zeromq,zstd}/install/lib \
 -L/usr/lib/aarch64-linux-gnu openpilot/common/libcommon.a -lzmq -ljson11
cp -a openpilot/common/libparams_c.so /tmp/libparams_c.so.bak-$(date +%s)   # 先备份
cp /tmp/libparams_c.so.new openpilot/common/libparams_c.so                   # 覆盖；运行中的进程仍持有旧 inode
```

注意 `params_c.os` 和 `libcommon.a` 用仓库里**已有的**产物即可，只需重编 `params.o` 这一个 TU。

## 验证（三条都要过）

```python
from openpilot.common.params import Params
p = Params()
print(p.check_key('CustomKp'), p.get_type('CustomKp'))        # b'CustomKp' 3(FLOAT)
p.put('CustomKp', 1.25, block=True); time.sleep(0.3)
print(repr(p.get('CustomKp')))                                # 1.25
p.remove('CustomKp')                                          # 回到未设置 -> read_float 回落 1.0
```

- 写后读要 `block=True` + 短睡眠：非阻塞读会先返回空（本次一度误判为「写不进去」）。
- 未知键仍必须抛 `UnknownKeyName`（证明校验没被削弱）。
- `params_keys_size()` 比旧库 +1（新键数）。

## 生效范围

新进程自动用新 .so（缓存文件名含 mtime+size）。**已经在跑的进程仍持有旧 mmap**，
所以车控进程（c-sd）与 ui 必须重启才认新键。offroad 时重启整套服务：

```bash
sudo systemctl restart comma
```

op-aid.service 不在 comma 的 cgroup 内，助手会话不会被这次重启带走。

## 2026-10-21 复盘：`-O1` 也不够，改成固定 `-O0`

把「配方」交给 scons 之前先量了峰值（`/usr/bin/time -v` 的 Maximum resident set size，
同一台机、同一 TU、同一组 `-I`，只有 `-O` 不同）：

| 优化级 | clang++ 峰值 RSS | 耗时 | 结果 |
|---|---|---|---|
| `-O2 -g`（scons 默认） | —（未跑完） | — | `Error -9`，dmesg: `Killing 'clang++' (610695) ... cache 4848kB is below limit` |
| `-O1 -g` | 1884940 kB ≈ 1.84 GiB | 68 s | 单跑能过（当时 MemAvailable 1872 MB，几乎顶满）；交给 scons 时被 `Error -9` 杀，dmesg 写的是 `to free 1817860kB on behalf of 'openpilot.sunny'` —— 不是 clang 自己涨爆，而是别的进程要 1.8 GB，LMK 挑了最大的 clang 下手 |
| `-O0` | 261616 kB ≈ 256 MiB | 34 s | 在满是守护进程的 offroad 机器上一次过 |

结论：`-O1` 的 1.84 GiB 在这台 3.6 GB 机器上不可复现地安全，`-O0` 才有 7 倍余量。
已落 `openpilot/common/SConscript`：只把 `params.cc` 这一个 TU 克隆出 `-O0` 环境编译，
其余 TU 仍是 `-O2`：

```python
_params_env = env.Clone(CCFLAGS=[f for f in env["CCFLAGS"] if f != "-O2"] + ["-O0"])
_params_obj = _params_env.Object("params.o", "params.cc")
_common = env.Library('common', ['swaglog.cc', 'util.cc', 'ratekeeper.cc', 'yuv.cc', _params_obj], LIBS="json11")
```

实测（本次）：`scons -j1 openpilot/common/libparams_c.so` → 38 s 一次过，
`[AR] libcommon.a` / `[LINK] libparams_c.so` 都正常，无 LMK。也就是这台机器上
「整机 scons 过不去」这条遗留项已经收口：手工编 `.o` 不再需要，`scons -n --verbose`
打印的 `params.o` 命令行里只有 `-O0`（无 `-O2`）。

## 关键坑：只重启 carrot_server 不够，manager 自己抱着旧 mmap

重建后杀掉 `carrot_server` 让 manager 拉起新进程，新进程（07:36:00 启动）**仍然**
mmap 旧的 `libparams_c-1792538280-1706104.so`，`check_key('WebPushVapid')` 抛
`UnknownKeyName`。原因是 manager（`python3 ./manager.py`，07:23:56 启动，早于重建）
自己 import 过 params，manager 拉子进程时子进程继承的是 manager 的内存镜像里的旧
`.so`，不会重新 `stat` 源文件。所以要 `sudo systemctl restart comma`（= 杀掉 tmux
`comma` 会话再起新 manager），让 manager 本身换到新库，子进程才跟着换。

验证姿势（三条，缺一不可）：

```bash
# 1) 子进程真的加载了新副本
grep params_c /proc/$(pgrep -f carrot.carrot_server | head -1)/maps | head -1
# 期望 .../libparams_c-<新mtime>-<新size>.so
# 2) 键表真的多出来
PYTHONPATH=/data/openpilot /usr/local/venv/bin/python3 -c \
  "from openpilot.common.params import Params; p=Params(); print(len(p.all_keys()), p.check_key('WebPushVapid'))"
# 3) 业务面真的认
curl -s http://127.0.0.1:7000/api/push/status
```

## 副作用 / 遗留

- `-O0 -g` 让 `libparams_c.so` 从 1.7 MB 涨到 2.87 MB（多出来的是 `-g` 调试信息与
  未优化的键表初始化代码）。这台机器的 `/data` 余量够，且 `.so` 只在 `common/` 留一份。
- 键表语义与 `-O2`/`-O1` 无差别；这里只有一堆 `std::unordered_map` 初始化与文件/zmq I/O。
- 以后 `params_keys.h` 每加一个键，都仍需「重建 + `systemctl restart comma`」两步；
  少了第二步的表现是**静默**的（新键在所有已跑进程里 `UnknownKeyName`）。

## 2026-10-21 收尾：钉子从 `-O0` 升到 `-O1 -g0`（1.9 GB 是 `-g` 吃的，不是 `-O1`）

上面那节把结论停在「`-O1` 不可复现地安全」，但漏了一个变量：`-O1 -g` 里的峰值主要来自
**调试信息**，不是优化本身。所以单量了一次去掉 `-g` 的同一 TU（同机、同 `-I`、只改
`-O`/`-g`，`nice -n 19`，每 200 ms 采 `/proc/<pid>/status` 的 `VmHWM`）：

| flag | clang++ 峰值 VmHWM | 耗时 | 结果 |
|---|---|---|---|
| `-O2 -g`（scons 默认） | —（未跑完） | — | `Error -9`，LMK 杀 |
| `-O1 -g` | 1884940 kB ≈ 1.8 GiB | 68 s | 单跑勉强过，交给 scons 被 LMK 杀 |
| **`-O1 -g0`** | **369924 kB ≈ 361 MiB** | **149 s** | **exit 0；全程 MemAvailable 最低 1013 MB 未触底** |
| `-O0 -g`（原钉子） | 261616 kB ≈ 256 MiB | 34 s | 过 |

结论：峰值从 1.8 GiB 掉到 361 MiB —— **5 倍**，那 1.4 GiB 全是 `.debug_*` 段。
`scons -j1 openpilot/common/libparams_c.so` 用新钉子实跑 2:53 一次过（含 `swaglog.o`
重编），`/usr/bin/time -v` 报 scons 进程 `Maximum resident set size: 369924 kB`，
与独立实测**逐 KB 吻合**，无 LMK。

已落 `openpilot/common/SConscript`（只钉 `params.cc` 一个 TU，其余仍 `-O2`）：

```python
_PINNED_OUT = {"-O0", "-O1", "-O2", "-O3", "-Os", "-g", "-g1", "-g2", "-g3", "-ggdb"}
_params_env = env.Clone(CCFLAGS=[f for f in env["CCFLAGS"] if f not in _PINNED_OUT] + ["-O1", "-g0"])
```

两个细节：

- 必须同时剔掉 `-g`（原钉子只剔 `-O2`，`-g` 留了下来，等于「-O0 -g」）。剔除用**精确
  集合**而不是 `startswith("-g")`，否则会误删 `-gcc-toolchain` 这类 flag。
- `-O1` 而不是继续 `-O0`：这个库在每个 daemon 的 param 读取路径上（`param_read`），
  `-O0` 会把 `unordered_map` 查找留在退化路径；`-O1` 只多花 115 s 编译时间（offroad 一次性），
  ABI 与语义不变。`-g0` 不损失什么：需要栈时按本节配方单独编一份带 `-g` 的临时 `.o` 即可。

验证（本次）：`scons -n --verbose -j1 openpilot/common/params.o` 打印的命令行里只有
`-O1 -g0`、无 `-O2`/`-g`；`openpilot/common/tests` + `openpilot/sunnypilot/common/tests`
共 **249 passed / 258 subtests passed**。

## 追加实测（2026-10-21 round 16，注册 NNFFMode 时）

同样单目标、同样 `-O1 -g0` pin（`ac4bc9fe07`），但这次开工前 `MemAvailable` 只有 **1337 MB**
（上文 361 MB 那次是 1.9 GB 充裕情形）：

```
scons -j1 openpilot/common/libparams_c.so
  Elapsed 2:31.90   Maximum resident set size 368940 KB  = 368.9 MB
  exit 0，无 LMK 记录
```

两点结论：

1. 峰值在 361–369 MB 之间（同一 TU，keys 数 671 → 731），量化判据可以用 **VmHWM < 500 MB**。
2. 存活条件不用「offroad MemAvailable > 1.9 GB」这么严：**1337 MB 也活**。建议判据放宽到
   `MemAvailable > 1.2 GB`，并把「1.9 GB」只当作历史记录而不是门槛。
3. 重建后自检（读私有副本，别读 checkout 里那份）：

```bash
python3 -c "from openpilot.common.params import Params; p=Params(); \
  ks={k.decode() for k in p.all_keys()}; print(len(ks), 'NNFFMode' in ks, p.get_type('NNFFMode'))"
# 731 True 2      # 2 = INT
```
