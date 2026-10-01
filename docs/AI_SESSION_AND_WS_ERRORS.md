# 建会话 500 / WS 事件收不到：两个并发与 schema 的坑

> 2026-10-01 实测修复。两个 bug 都**静默**——一个报 500，一个干脆把整帧丢掉。

## 1) `POST /api/ai/sessions` 500：原子写的临时文件被"清尾"删掉了

```
aid: unhandled POST /api/ai/sessions: [Errno 2] No such file or directory:
  '/data/ai/.ai_config_4p1zbvd4' -> '/data/ai/config.json'
```

`ai/common/config_store.py::_save_disk()` 的流程是
`清理旧的临时文件 → mkstemp(".ai_config_*") → os.replace()`。
清理那一步是**按前缀无条件删除**：

```python
for path in parent.glob(".ai_config_*"):
    path.unlink()          # ← 把别的线程刚 mkstemp 出来的文件也删了
```

于是并发写时：A 建好 temp → B 清尾把它删掉 → A 的 `os.replace` 抛 `ENOENT`。
表现就是建会话偶尔/频繁 500（配置读出又写回，很容易并发）。

修法（两条一起上）：

1. 清尾只删**过期的**：`mtime` 早于 60s 才删（`_STALE_TEMP_SEC`），刚创建的跳过；
2. `os.replace` 包一层**重试一次**，兼容"还在跑老代码"的进程（比如没重启的 daemon）。

验证：6 线程 × 60 次并发写，0 异常、无残留 temp。

## 2) WS `chat_status` 整帧被丢掉：`error` / `resolvedModel` 不该发 null

```
aid: ws schema validation: chat_status.error: expected string
```

`ai/core/sync/protocol.py` 里 `chat_status` 的 schema 把 `error`、`resolvedModel` 声明成 **string**、
`assistant` 声明成 **object**，只有 `type/jobId/sessionId/status` 是 required。
而生产者 `notify_chat_status()` 直接 `"error": job.get("error")` —— 没有错误时就是 `None`，
校验失败，**hub 把整帧丢掉**，于是前端永远收不到"任务完成"。

坑中坑：校验器**只报第一个错误**。把 `error` 修好后立刻冒出
`chat_status.resolvedModel: expected string` —— 所以要按 schema 逐个字段核对：

```python
from ai.core.sync.protocol import validate_ws_message
validate_ws_message({"type":"chat_status", ..., "error":None})
# (False, 'chat_status.error: expected string')
```

修法：抽出 `chat_status_frame(job_id, session_id, job)`，
**optional 字段为 None 就整个不发**（而不是发 null），字符串字段非 str 时 `str()`；
status 缺失兜底 `"queued"`。回归测试：`ai/tests/test_chat_status_frame.py`
（对多种 job 形状逐个跑 `validate_ws_message`）。

## 经验法则

- schema 校验失败是**丢帧**，不是降级：前端表现为"没反应"，日志里只有一行 warning —— 别忽略它。
- 修 schema 报错要**修到校验器全绿**，因为一次只报一个错。
- 原子写 + 按前缀清尾 = 并发定时炸弹；清尾必须有时效判据。
