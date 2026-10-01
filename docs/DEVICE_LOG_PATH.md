# 设备日志路径 & ai 取日志工具（dp_dev_last_log / swaglog.*）

> 现象：`grep_log` / `read_manager_log` 直接失败，报
> `Tool execution failed: b'dp_dev_last_log'`，于是"拿不到最新日志"。

## 两个叠加的 bug（2026-10-01 实测修复）

### 1) `params.get("dp_dev_last_log")` 抛 UnknownKeyName

openpilot 的 `Params.get()` 会先 `check_key()` 校验 key 是否在**已注册 key 列表**里；
`dp_dev_last_log` 在有些 build 上**根本不是合法 key** → 直接抛
`openpilot.common.params.UnknownKeyName: b'dp_dev_last_log'`（注意参数是 **bytes**，所以报错里带 `b'...'`）。

因为没被捕获，异常穿透整个工具 → 工具整体失败，**永远走不到 `/data/log` 兜底**。
（对照：`read_params` 这种管理类工具容忍未知 key，返回 `null`。两条代码路径校验不同，
所以会出现"`read_params` 显示 null 但 `grep_log` 直接崩"。）

修：`ai/tools/domains/core/diagnostics_tools.py::_read_device_log()` 把 `params.get` 包 try/except，
读不到就往下走。

### 2) `dev_log_path()` 车机分支硬编码 `/data/log/latest.log`，而该文件不存在

这台 AGNOS 上**没有** `latest.log`、没有符号链接，真实日志是滚动的 NDJSON：
`/data/log/swaglog.0000000157` 这种。用错路径 = 永远取不到内容。

修：`ai/system/paths.py::dev_log_path()` 车机分支改为取 `/data/log` 下 **mtime 最新的 `swaglog.*`**，
只有在完全没有 `swaglog.*` 时才回退 `latest.log`。

```python
if is_comma_device():
  log_dir = Path("/data/log")
  if log_dir.is_dir():
    logs = sorted(log_dir.glob("swaglog.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if logs:
      return str(logs[0])
  return "/data/log/latest.log"
```

## 验证

```sh
python3 -c "import sys; sys.path.insert(0,'/data/openpilot'); from ai.system.paths import dev_log_path; print(dev_log_path())"
# -> /data/log/swaglog.0000000157
```
然后 `read_manager_log(lines=15)` 应返回 `"source": "/data/log/swaglog.0000000157"`，
`grep_log` 不再报 `dp_dev_last_log`。

## 经验法则

- **先量再改**：工具报错信息本身就是根因线索（这里的 traceback 直接指到 `diagnostics_tools.py:48`）。
- 工具失败时**不要**用历史结论冒充新证据；先把取数工具修好，再诊断。
- 日志是 NDJSON 文本（`swaglog.*`），`tail` / `grep` 直接可用。

## 相关

- `ai/docs/UI_FREEZE_WEBUI_BLOCKING.md`（同一会话定位的另一个真因）
