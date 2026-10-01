# WebUI 的 AGNOS install 为什么"点了没反应"

## 一句话结论

`webui/server/bridge/agnos_api.py` 的 `_openpilot_dir()` 在 **monorepo 布局**下返回了仓库根目录，
于是 `_agnos_py()` 拼出一个**不存在**的路径，`_run_agnos_swap()` 里的 `subprocess.Popen()` 直接
抛 `FileNotFoundError`，安装线程在真正执行 `agnos.py --swap` 之前就死了。

## 复现证据（只看事实）

设备布局：`BASEDIR` = `/data/openpilot`（monorepo 根），openpilot 包在 `/data/openpilot/openpilot`。

```
$ python3 -c "from openpilot.common.basedir import BASEDIR; print(BASEDIR)"
/data/openpilot

$ ls /data/openpilot/common/hardware/comma/agnos.py          -> NO
$ ls /data/openpilot/openpilot/common/hardware/comma/agnos.py -> YES
```

改之前跑一遍模块里的函数：

```
_openpilot_dir()  -> /data/openpilot
_agnos_py()       -> /data/openpilot/common/hardware/comma/agnos.py   exists: False
```

改之后：

```
_openpilot_dir()  -> /data/openpilot/openpilot
_monorepo_root()  -> /data/openpilot
_agnos_py()       -> /data/openpilot/openpilot/common/hardware/comma/agnos.py  exists: True, exec: True
_target_agnos_ver()-> 19.8-carrot-bt2
manifest          -> /data/openpilot/openpilot/common/hardware/comma/agnos.json  exists: True
```

## 根因：同一个函数的两条分支语义不一致

```python
def _openpilot_dir() -> Path:
  try:
    from openpilot.common.basedir import BASEDIR
    return Path(BASEDIR)              # ← 分支 A：直接返回 BASEDIR
  except Exception:
    root = Path(OPENPILOT_ROOT or parents[3])
    if (root / "openpilot").is_dir():
      return root / "openpilot"       # ← 分支 B：有"往下一层找 openpilot 包"的归一化
    return root
```

只有 `except` 分支做了归一化。上游（非 monorepo）布局里 `BASEDIR` **就是**包目录，所以分支 A 在上面
跑不出问题；本 fork 是 monorepo，`BASEDIR` 是仓库根，于是分支 A 必然错。

**判断法则**：判断"哪个目录是 openpilot 包目录"，不要靠目录名字，靠标记文件 ——
`<base>/openpilot/common` 存在，则 `<base>/openpilot` 才是包目录。

## 修复（webui a020322）

```python
def _openpilot_dir() -> Path:
  """Directory that holds the openpilot python package (cereal, common, ...)."""
  try:
    from openpilot.common.basedir import BASEDIR
    base = Path(BASEDIR)
  except Exception:
    base = Path(os.environ.get("OPENPILOT_ROOT") or Path(__file__).resolve().parents[3])

  if (base / "openpilot" / "common").is_dir():
    return base / "openpilot"
  return base
```

`_monorepo_root()` 不用改：它拿到包目录后靠 `parent/launch_env.sh` 反推回仓库根，
monorepo 下得到 `/data/openpilot`，上游布局下退回 `BASEDIR` —— 两种布局都对。

## 排查时别踩的坑

| 现象 | 不要误判成 | 实际 |
|------|-----------|------|
| 点 install 没反应 | 不是前端按钮 / JS 的问题 | 后端线程起来后立刻 `FileNotFoundError`，状态被写成 `failed` |
| 状态一直是 `idle` | 不一定是没点 | `start_agnos_install()` 在 `update_required == False` 时直接返回 `{"ok": False, "error": "not_required"}`，前端若没提示就"看起来没反应" |
| `/tmp/agnos_webui.log` 不存在 | 不代表没触发 | 日志文件是在 `Popen()` **之后**才创建的；`Popen()` 抛异常时它永远不会出现 |

最后一条尤其重要：**日志文件缺失恰恰是"进程没起来"的证据，而不是"根本没跑"的证据。**

## 怎么自己验一遍

```python
import importlib.util, sys, os
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/webui")
spec = importlib.util.spec_from_file_location("agnos_api", "/data/openpilot/webui/server/bridge/agnos_api.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m._openpilot_dir(), m._agnos_py(), os.path.isfile(m._agnos_py()))
```
