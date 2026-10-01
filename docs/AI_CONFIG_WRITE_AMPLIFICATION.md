# 离车发热（二）：AI 配置库把「存一个键」做成「重写 5 MB」

> 场景：车没在跑（`driving=false`），SoC 60+°C，`aid` 进程 CPU 长时间 30%~110%。
> 2026-10-01 实测定位，数字都是本机量出来的。

## 一句话结论

`/data/ai/config.json` 是**单个 5 MB 的 JSON blob**，而 `AiConfigStore._save_disk()`
每次都把**整份** `json.dumps(..., sort_keys=True)` 后原子写盘。
Web 端约 **每 2.2 s** 同步一次会话（写 `ai_web_sessions`），
于是：**写 1 个键 = 序列化 + 写盘 5 MB，每 2.2 s 一次 ≈ 2 MB/s 持续写 + 1/3 单核**。

## 实测证据

`config.json` 体积构成（5,016,415 B，18 个顶层键）：

| 键 | 大小 |
|----|------|
| `ai_web_sessions` | **3612 KB** |
| `ai_rag_documents` | 1379 KB |
| `ai_evolution_pipeline_log` | 13.9 KB |
| 其余 15 个键合计 | < 30 KB |

| 指标 | 实测值 |
|------|--------|
| `config.json` 重写频率 | **20 s 内 9 次（~2.2 s/次）** |
| `/proc/<aid>/io` `write_bytes` 速率 | **2035 KiB/s**（10 s 采样） |
| `write_bytes` 累计 | 743 MB（进程重启后 6 分钟内已 542 MB） |
| `aid` CPU | **33%（5 s 均值）**，峰值 110% |
| `config.json` mtime | 与采样时刻同步刷新（08:13 → 08:14） |

## 因果链（逐段都能验）

```
Web 客户端（~2.2s 一次）
  → POST /api/ai/sessions
  → ai/tools/domains/platform/session_store.py::save_sessions()
  → write_param(params, "ai_web_sessions", json.dumps(<3.6 MB>))   # 值本身是 JSON 字符串
  → ai/common/config_store.py::AiConfigStore.put()
  → _save_disk(): json.dumps(整份 5 MB, sort_keys=True)
  → mkstemp(".ai_config_*") + os.replace()      # 每次都是全量
```

注意 **3.6 MB 的会话是作为「字符串」嵌在 JSON 里的**：既被二次转义，又让"只改会话"
也必须重排/重写整份配置。这是和 `verify_agnos_update()` 同一类病：
**高频触发、全量、未按变化范围收敛**。

## 量法（复现）

```sh
# 1) 谁在写
ps -eo pid,pcpu,comm,args --sort=-pcpu | head
awk '/^write_bytes/{print $2}' /proc/$(pgrep -f 'ai.aid')/io     # 两次采样求差
# 2) 是不是这个文件在被反复重写
f=/data/ai/config.json; prev=""; for i in $(seq 1 20); do c=$(stat -c '%Y %s' $f); \
  [ "$c" != "$prev" ] && echo "rewrite $c"; prev=$c; sleep 1; done
# 3) 体积构成（找出谁把 blob 撑大）
python3 -c "import json,sys; d=json.load(open('/data/ai/config.json')); \
print(sorted(((len(json.dumps(v,ensure_ascii=False)),k) for k,v in d.items()),reverse=True)[:5])"
```

## 修法方向（**未改，需确认**）

按收益排序：

1. **把会话数据搬出 `config.json`**（单独文件 / 追加式日志）。这是根治：静态配置只有 <30 KB，
   重写它本来是廉价的。`ai_session_logs/*.jsonl` 已有追加式落盘，会话没必要再塞进 Params 大 blob。
2. **写前脏检查 + 合并写**：`_save_disk` 若序列化结果与上次一致就直接返回；
   并把 200~500 ms 内的多次 `put()` 合并成一次写。
3. 值不要再存"JSON 字符串"（现在是二次转义），改存结构化对象。

> 只做 2 不够：合并后单次仍是 5 MB 全量。1 才是把量级降下来的那一步。

## 相关

- `ai/docs/PERF_HOTSPOTS.md`（同类热点清单，含 `models.manager` 每秒解析）
- `ai/docs/UI_FREEZE_WEBUI_BLOCKING.md`（同一次定位的 webui 事件循环阻塞）
- `ai/docs/AI_SESSION_AND_WS_ERRORS.md`（同一个 config store 的并发原子写 bug）
