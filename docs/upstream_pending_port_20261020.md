# 上游已实现、我们未移植 —— 清单 + 检查器（2026-10-20）

## 1. 这次的坐标

| | commit | 说明 |
|---|---|---|
| 我们 | `c14a63ea20` | sp-macan-test（2026-10-20 12:5x，END_SOFT_RATE 跟随上游后） |
| 上游 | `817f4a78c2` | mouxangithub/openpilot `test`，2026-10-20 17:30 (+0800) |
| 审计范围 | `59efe220e6..817f4a78c2` | 今天这一批 **35 个提交** |

`git cherry HEAD upstream/test` 对这 35 条全给 `+`，即**没有一条的补丁本身在我们树里**。
其中少数条目我们已经用别的写法实现过意图（例如 params 键 `CarrotLongitudinalSourceEnabled` 已在
`params_keys.h:473`，缺的只是 UI 项），但代码级都还不在。

## 2. 两条腿：登记表 + 探针

`ai/docs/upstream_divergence_registry.json` 新增第二段 `upstream_pending_port`：

```jsonc
{
  "commit": "...", "subject": "...", "group": "...", "status": "todo|todo-after|eval|pointer|docs",
  "impact": "对我们有什么影响", "next": "搬的时候先干什么",
  "probes": [ {"kind": "path_absent", "target": "openpilot/...", "needle": null} ]
}
```

`probes` 是**「它现在还没被移植」的机器判据**，不是愿望：

| kind | 现在成立的条件 | 含义 |
|---|---|---|
| `path_absent` | 文件不存在 | 上游的新文件我们还没有 |
| `path_present` | 文件还在这 | 上游那次是**删除**（例如 `carrot_man_input.py`） |
| `symbol_absent` | 文件里搜不到该符号 | 上游加的函数/字段/键我们还没有 |
| `symbol_present` | 文件里还有该符号 | 上游那次是**移除**（例如 `auto_update._notify_cwp`） |
| `submodule_not_ancestor` | 该 pin 不是子模块 `HEAD` 的祖先 | 子模块指针还没跟上 |

判据失效 = `DRIFT`（我们其实搬了，或上游又改了）→ 回来改表，**不要**继续相信这张清单。

状态分布：`todo` 10 / `todo-after` 8（依赖同批其它条目）/ `eval` 9（体积大或要驾驶者决策）/
`pointer` 6（jetlink 5 连 + opendbc）/ `docs` 2。

值得先看的四条：
- `0429a86b67` 红灯 latch 在 5 km/h 以上没有退役 → 前车在速度下消失会把红灯 veto 重新按上来（真 bug）。
- `0fa33738ca` proclog 缓存改按 `starttime` 身份索引 + 资源前 `gc.freeze()`（我们仍按 PID，PID 复用会串数）。
- `6ad1f5b099` 导航 GPS 来源收口到一个模块（我们 `carrot_serv` 里还是散装判断）。
- `4f4256c37b` 一半是纯删除：`auto_update._notify_cwp` 那条没人要的回传，我们还在跑。

## 3. 顺手修掉的坑：`remote.upstream.fetch` 只盯一个分支

我们这份 `.git/config` 里原本是：

```
remote.upstream.fetch = +refs/heads/master-c3:refs/remotes/upstream/master-c3
```

也就是说 `git fetch upstream` **只会取 `master-c3`**，`test` 怎么动都不动，`FETCH_HEAD` 不动 ⇒
看起来永远「无更新」。这就是上一轮误判「上游没有更新」的直接原因。

已改成通配：

```
git config remote.upstream.fetch '+refs/heads/*:refs/remotes/upstream/*'
```

这条只活在 `.git/config`（不随仓库走），所以检查器加了 **phase 0** 自己看守：refspec 不是通配就
`WARN` 并非零退出；`--fix-fetch` 一键修回。换机 / 重刷后跑一次检查器就知道有没有被带回旧配置。

## 4. 怎么用

```bash
python3 ai/scripts/upstream_divergence_check.py                # phase 0+1+2
python3 ai/scripts/upstream_divergence_check.py --pending-only  # 只看「未移植」35 条
python3 ai/scripts/upstream_divergence_check.py --fix-fetch     # 修 remote.fetch 后继续
python3 ai/scripts/upstream_divergence_check.py --only stopping_controller.py
python3 ai/scripts/upstream_divergence_check.py --json
```

当前：`phase 0 OK` / `phase 1 => 9/9 as expected` / `phase 2 => 35/35 still unported as recorded`。

## 5. 重新以上游为基底时的用法

1. 先 `--fix-fetch` + `git fetch upstream`，确认 `upstream/test` 真的到最新。
2. 判断清单是否过期：跑 phase 2，`DRIFT` 的那些说明「已经搬过或上游改了」，先改表。
3. 重基线时**按 group 逐组搬**（`pointer` 先搬子模块，再 `docs`/`todo-after`），每搬一条把
   该条 `status` 从 `not_ported` 状态改成 `ported`（或直接从 `items` 里删掉并记一笔），
   探针随即反转成 `DRIFT` —— 这是「不漏也不重」的唯一可靠信号。
4. `expect_diff: true` 的 9 个文件（phase 1）永远不能被上游覆盖：那是我们的分叉本体。
