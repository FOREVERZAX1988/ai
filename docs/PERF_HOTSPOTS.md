# 离车还在吃 CPU 的热点（实测）

> 场景：车停着、不在跑，`load average` 却下不来，SoC 60+°C。
> 结论要**先量再改**：下面每条都带实测数字。

## 1) `sunnypilot.models.manager`：1 Hz 主循环每次重新解析模型目录（约 76 ms/次）

`openpilot/sunnypilot/models/manager.py::main_thread()` 是 `Ratekeeper(1)` 的**每秒**循环，
每一轮都无条件重做这些事（**不看是否离车、也不看目录有没有变**）：

```python
self.source_models = {source: self.model_fetcher.get_bundles_for_source(source)
                      for source in ModelFetcher.MODEL_SOURCES}   # ← 热点
self.available_models = self.source_models[ModelFetcher.active_source(self.chestnut_present)]
validate_active_bundles(self.params, self.source_models)
self.active_bundle = get_active_bundle(self.params, chestnut=self.chestnut_present)
```

实测（2026-10-01，本机，停车状态）：

| 步骤 | 耗时 |
|------|------|
| `get_bundles_for_source` ×2（qcom + chestnut，共 77 个 bundle） | **72.4 ms** |
| `validate_active_bundles` | 4.0 ms |
| `get_active_bundle` | ~0.0 ms |
| **每轮合计** | **76.4 ms → 约 7.6% 单核持续占用** |

配套观测：`ps` 里 `models.manager` 稳定 15.6% CPU；`/proc/<pid>/io` 的 `rchar` 已累计 1.4 GB；
**没有**网络连接、没有 `.part`/`.tmp` 下载文件、模型目录 10 分钟内无写入 —— 所以**不是在下模型**，
就是在反复解析/校验同一份目录。

修法方向（未改，需确认）：按 `mtime` / 相关 Params 变化缓存 `get_bundles_for_source()` 的结果，
或者离车时把循环降到 0.2 Hz。注意历史提交 `a497def49 perf(models): parse the cached model catalog
only when it changes` 只优化了"解析缓存目录"的一部分，上面这条**每秒仍然全量跑**。

## 2) webuid 的状态轮询（已修，见另一篇）

同类问题、已在本机修掉：见 `docs/UI_FREEZE_WEBUI_BLOCKING.md`（未缓存的
`verify_agnos_update()` 每次约 400 ms 块 IO，直接把 webui 事件循环堵死，约 12.6% CPU）。

## 量法（复现）

```sh
# 1) 谁在吃 CPU（瞬时，别只看 ps 的 lifetime 平均值）
ps -eo pid,pcpu,comm,args --sort=-pcpu | head
# 2) 它到底在干活还是在下东西
ls -l /proc/<pid>/io ; ss -tnp | grep <pid>
# 3) 直接给"每一轮"计时（本例）
PYTHONPATH=/data/openpilot:/data/.pydeps:/usr/local/venv/lib/python3.12/site-packages python3 - <<'EOF'
import time
from openpilot.common.params import Params
from openpilot.sunnypilot.models.fetcher import ModelFetcher
from openpilot.sunnypilot.models.helpers import validate_active_bundles, get_active_bundle
p = Params(); f = ModelFetcher(p)
t0 = time.perf_counter()
src = {s: f.get_bundles_for_source(s) for s in ModelFetcher.MODEL_SOURCES}
t1 = time.perf_counter()
validate_active_bundles(p, src); get_active_bundle(p, chestnut=False)
t2 = time.perf_counter()
print(f"per tick: {(t2-t0)*1000:.1f} ms -> ~{(t2-t0)*100:.1f}% of one core at 1 Hz")
EOF
```

> 顺带：`lmh-dcvs-00/01 = 75°C` 是高通 LMH 的**门限配置值**，不是实测温度；
> 真正要看 `cpu silver/gold`、`gpu`、`msm-therm` 那几个。
