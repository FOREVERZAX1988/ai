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

## 第二个坑（就是上表第二行）：`not_required` 现在有提示了（webui `040a1b1`）

上表第二行写"前端若没提示就'看起来没反应'"—— 这一格 2026-10-01 补上了。实测它确实在骗人：

```
$ curl -s -X POST http://127.0.0.1:5080/api/opui/agnos/install
{"ok": false, "error": "not_required"}

$ curl -s http://127.0.0.1:5080/api/opui/agnos
{"ok": true, "available": true, "current_version": "19.8-carrot-bt2",
 "target_version": "19.8-carrot-bt2", "update_required": false, ...}
```

`/VERSION == AGNOS_VERSION` → `update_required=false` → **服务端根本没有可装的东西**。
但前端把事情做成了：先乐观弹一个整屏遮罩，拿到 `ok:false` 后把裸错误码 `not_required`
贴到 "Update failed" 上。裸码 + 整屏失败页 = 和"按钮坏了"完全无法区分（这个现象被报过两次）。

**修法**：把"不是失败"的码当信息处理 —— 关掉自己刚打开的那层遮罩，改成一句人话的 toast。

`web/static/js/system_wait_overlay.js`：

| 码 | 含义 | 现在的表现 |
|---|---|---|
| `not_required` | 已是最新版本 | toast「无需更新 — 本机已是最新 AGNOS 版本，无需安装。」 |
| `not_agnos` | 设备不支持 | toast「无法进行 AGNOS 更新 — 本设备不支持 AGNOS 更新。」 |
| `not_ready` | 尚未就绪 | toast「更新尚未就绪 — AGNOS 更新尚未准备好安装，请稍后重试。」 |

其余错误码仍走原来的失败遮罩。文案是 WebUI 专用键，放 `i18n.js` 的 `LOCAL_FALLBACKS`（en / zh-CHS / zh-CHT）。
`home.js` 在 `runAgnosUpdateFlow()` 返回后本来就会 `refreshHomeScreen()`，所以卡片也会跟着刷新掉。

### 附带的坑：改了 JS 还必须让**浏览器**重新加载

`system_wait_overlay.js` 原来是**不带版本号**引入的，浏览器按 URL 缓存 —— 磁盘上改了 ≠ 设备上生效，
和"补丁提交了 ≠ 进程重启了"（见 `UI_FREEZE_WEBUI_BLOCKING.md`）是同一类错。所以要么不修，
要么同一提交里把缓存键抬掉：

| 位置 | 改动 |
|---|---|
| `web/static/js/app.js`、`home.js`、`panels.js` | `system_wait_overlay.js` → `?v=2`；**三处必须一起改且一致**，否则浏览器会实例化两份模块，`active` / `abortCtrl` 状态分裂 |
| 全部 23 处 `from "./i18n.js?v=3"` | → `?v=4` |
| `web/static/index.html` | `app.js?v=134` → `?v=135` |

## 发布与分支对齐（2026-10-01 收尾）

| 仓 | 提交 | FZ:`master-c3` | 校验 |
|---|---|---|---|
| `FOREVERZAX1988/webui` | `040a1b1` fix(agnos): say so when there is nothing to install | `381be33..040a1b1`（快进，无 `--force`，`--no-verify`） | 远端 SHA == 本地 HEAD ✅ |

之前推的是**新分支** `sp-macanlong-1001`，而 `.gitmodules` 里写的是 `branch = master-c3` ——
`FZ/webui:master-c3` 当时停在 `381be33`，于是"按 `.gitmodules` clone"和"按推的分支 clone"会拿到不同代码。
这一步把 `FZ/webui:master-c3` 快进到 `040a1b1`（顺带带上 `a020322`），两条线对齐。
