# 巡航面板 5 个 DEC 开关 + 安全模式四条回到中文（根因：提取器看不见裸字符串）

> 触发：驾驶者报「巡航里原本是中文的几个 UI 变英文了：DEC: Curves、Slower Lead、Turn Signal、
> Stops Ahead、Low Speed Creep；设备选项里还有 Enable Safe Mode」。
> 父仓提交：`20a453139a`（分支 `sync/upstream-1024`）。

## 1. 结论先行

不是 po 文件丢了译文，是这 10 条**从来就没进过 `app.pot`**：

- `selfdrive/ui/sunnypilot/layouts/settings/alpha_longitudinal_toggles.py` 把五个开关的标题/描述
  放在 `_dec_trigger_specs` 的**裸字符串元组**里，运行期用 `tr(t)` / `tr(d)` 拿变量去查。
- `potools.extract_strings()` 走 AST，只认 `tr() / trn() / tr_noop()` 的**字面量实参**；
  `tr(t)` 的实参是变量 `t`，`_eval_string_node()` 返回 `None`，该条被静默跳过。
- 于是 `tr()` 查不到就返回原串，UI 兜底英文。同面板其他文案（`Experimental Mode Speed Assist`
  等）是 `tr("...")` 字面量，所以一直有中文——唯一差异就是这个写法。

`Enable Safe Mode` 是另一类：msgid 早在 pot 里，但 `app_zh-CHS.po` / `app_zh-CHT.po` 的
`msgstr ""` 空着（连同 `Exit Safe Mode` 和两段确认、一段撤销，共 5 条）。

## 2. 改法

| 文件 | 改动 |
|---|---|
| `alpha_longitudinal_toggles.py` | 五组标题/描述全部包 `tr_noop(...)`（静态可提取、运行期再翻），与同文件 `EXPERIMENTAL_MODE_DESCRIPTION` 的既有写法一致；运行期仍走 `tr(t)`，行为不变 |
| `app.pot` | 补登这 10 条 msgid（`#: .../alpha_longitudinal_toggles.py`） |
| `app_zh-CHS.po` / `app_zh-CHT.po` | 补登 10 条译文 + 填上 5 条安全模式空 msgstr |

`tr_noop` 只是「标记」：`def tr_noop(s): return s`。它不进运行期查表，只让提取器看见，
所以下次 `update_translations.py` 重新生成 pot 不会再把这几条扫丢。

## 3. 复验（都是本机实跑）

- `potools.extract_strings()` 对该文件 → 10/10 条 DEC 家族 msgid 可提取。
- `parse_po()`：zh-CHS / zh-CHT 对这 15 条 msgstr 全部非空。
- `multilang.load_translations('app_zh-CHS.po')` 实跑 `tr()`：
  `DEC: Curves → DEC: 弯道`、`Enable Safe Mode → 启用安全模式` 直接命中。
- `pytest openpilot/selfdrive/ui/tests/test_translations.py` → **48 passed**。
- `ruff check` 该源码文件 → All checks passed。

## 4. 生效方式（不用重刷镜像）

`Multilang.setup()` 在语言切换时重读 po（`change_language()` / `reload()`）。
所以设置里把语言切到 English 再切回中文即实时重载；也可以等下一次重启 UI。

## 5. 余量（单独一批，未动）

pot 里仍有空 msgstr：**zh-CHS 33 条 / zh-CHT 34 条**（38/39 − 本轮 5 条）。绝大多数是
`carrot_tuning_items.py` 的长调参描述（限速解析、coasting 带宽、cut-in 抑制等），另有
`{} minute ago` / `{} hour ago` / `{} day ago` / `{}% on disk` / `{} ALERT` 这类短串。
这批不需要改源码，纯填 po。

## 6. 顺带核实（同轮）

- 重启后 `ExperimentalMode=True` / `ExperimentalModeConfirmed=True` 双键都在，实验模式不再掉。
- 上游 `test` 仍是 `684178cb51`，registry 未移植只剩 2 条：panda 指针 `eeb028a58`（真活儿，
  需单独一轮 + 上车验）与基座合并 `564e8e93c8`（`no-port`）。
