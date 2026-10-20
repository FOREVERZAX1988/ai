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
（`-O0` 实测峰值 ≈ 240 MB，`-O1 -g` 也能过 —— 只有 `-O2 -g` 会死。）

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

## 副作用 / 遗留

- 手工编出的 `params.o` 不带 scons 签名，下次任何人跑 `scons` 会重新用 `-O2 -g` 编
  `params.o` 并再次被 LMK 杀掉（失败在建 `.o` 阶段，不会破坏已存在的 `libparams_c.so`）。
  要长期干净，得给 `SConstruct` 的 host 编译加内存友好的例外（例如对
  `openpilot/common/params.cc` 固定 `-O1`），否则这台机器上「整机 scons」始终过不去。
- `-O1` vs `-O2` 对键表语义无差别；这里只有一堆 `std::unordered_map` 初始化与文件/zmq I/O。
