# 车况全是 0 / `reader_unavailable: true`：`cereal` 的导入方式在这棵树上不一样

> 现象：`get_vehicle_state` 返回 `reader_unavailable: true`，v_ego / ignition / car_fingerprint 全空；
> 日志里只有一行 `aid: cereal.messaging not available (state reader disabled)`。
> **这不是"车熄火了"，也不是"重启 aid 就好了"。**（2026-10-01 实测）

## 根因：monorepo 里没有顶层 `cereal` 模块

- 上游 openpilot 把 `cereal` 放在**仓库根**，所以代码里写的都是 `from cereal import messaging`。
- 这棵 fork 是 **monorepo**：openpilot 的代码树在仓库下**一层**（`openpilot/`），
  它自己的代码用的是**包名限定**的写法 —— 见 `openpilot/system/manager/manager.py`：
  `import openpilot.cereal.messaging as messaging`。
- 设备上的 `PYTHONPATH=/data/openpilot:/usr/local/venv/lib/python3.12/site-packages:/data/.pydeps`
  **不含** `/data/openpilot/openpilot`，所以 `import cereal` 直接 `ModuleNotFoundError`。

实测：

```sh
ls -d /data/openpilot/cereal            # No such file or directory
find /data/openpilot -maxdepth 2 -name 'cereal*'   # 只有 openpilot/cereal
PYTHONPATH=<device PYTHONPATH> python3 -c "import cereal"
#   ModuleNotFoundError: No module named 'cereal'
```

`ai/selfdrive/state.py` 当年写的是 `try: from cereal import messaging / except ImportError: messaging = None`
→ 静默降级成"没有消息系统"，于是 `StateReader` 永远禁用。

## 修法：兼容两种布局

`ai/common/cereal_compat.py`：

```python
def import_cereal(submodule: str = ""):
  for prefix in ("openpilot.cereal", "cereal"):   # 先包名限定，再回退上游写法
    try:
      return importlib.import_module(f"{prefix}.{submodule}" if submodule else prefix)
    except ImportError:
      continue
  raise ImportError(...)
```

所有 `from cereal import X` / `from cereal.services import Y` 改成
`X = import_cereal("X")`（本仓共 7 处：state、cabana/deps、cabana/car_params、
live_tools、system_info_tools、diagnostics_tools、scripts/split_cabana_app）。

## 验证

```sh
PYTHONPATH=/data/openpilot:/usr/local/venv/lib/python3.12/site-packages:/data/.pydeps python3 -c "
from ai.selfdrive.state import StateReader
r = StateReader(); print(r._healthy, r._services)"
# -> True ['deviceState','pandaStates','carState','controlsState','carParams','selfdriveState','onroadEvents','managerState']
```

`get_vehicle_state` 之后应返回 `reader_unavailable: false`（字段值仍可能全是 0 —— 停车时本来如此，
别把"停车"误判成"读不到"）。

## 经验法则

- 报错"某模块不可用"时，**先确认这个模块在这棵树里到底叫什么名字**，别照抄上游的 import。
- 这台设备上仍有两个独立问题会被误认成同一个：**msgg/msgq 未编译**（历史问题，现已好）
  和 **cereal 布局**（本条）。判断标准就是那行日志的原文。

## 相关

- `ai/docs/TROUBLESHOOTING.md`
- `ai/docs/AI_SESSION_AND_WS_ERRORS.md`（同批修的会话 500 与 WS schema 问题）
