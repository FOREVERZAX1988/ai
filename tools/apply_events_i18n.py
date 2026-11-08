#!/usr/bin/env python3
"""把上游汉化的 events alert 文案重放为英文 msgid，并同步中文 po。

老规矩每轮合并上游 mouxa/test 之后跑一次即可：上游是中文汉化分支，若不做
这一步，i18n_check 会重新报出几百处硬编码中文，语言切换也会重新失效。

用法：
  python3 ai/tools/apply_events_i18n.py --check   # 只校验，不改文件
  python3 ai/tools/apply_events_i18n.py           # 重放源码 + 回填 po

映射表的单一数据源是 openpilot/selfdrive/ui/translations/events_i18n.py。
"""
from __future__ import annotations

import argparse
import ast
import os
import sys

BASEDIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASEDIR)

from openpilot.selfdrive.ui.translations.events_i18n import (  # noqa: E402
  CONST_MAP, FRAG_MAP, TPL_MAP, po_entries, inject_po,
)

EVENTS_FILES = [
  "openpilot/selfdrive/selfdrived/events.py",
  "openpilot/sunnypilot/selfdrive/selfdrived/events.py",
  "openpilot/sunnypilot/selfdrive/selfdrived/events_base.py",
  "openpilot/sunnypilot/selfdrive/selfdrived/events_zp.py",
]
PO_LANGS = ["zh-CHS", "zh-CHT"]
TRANSLATIONS_DIR = "openpilot/selfdrive/ui/translations"


def _has_cn(s: str) -> bool:
  return any("\u4e00" <= c <= "\u9fff" for c in s)


def _map_const(value: str, in_fstring: bool) -> str:
  if in_fstring and value in FRAG_MAP:
    return FRAG_MAP[value]
  if value in CONST_MAP:
    return CONST_MAP[value]
  raise KeyError(f"映射表缺少中文文案: {value!r} (f-string={in_fstring})")


def _rebuild_fstring(node: ast.JoinedStr) -> str:
  """把 f-string 的中文片段换成英文片段，保留全部表达式与格式说明。"""
  for part in node.values:
    if isinstance(part, ast.Constant) and isinstance(part.value, str) and _has_cn(part.value):
      part.value = _map_const(part.value, True)
    elif isinstance(part, ast.FormattedValue):
      # f"...{'公里/时' if metric else '英里/时'}..." 里的内嵌文案也要还原
      for sub in ast.walk(part):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and _has_cn(sub.value):
          sub.value = _map_const(sub.value, False)
  return ast.unparse(node)


def transform(path: str, apply: bool) -> tuple[int, list[str]]:
  with open(path, "rb") as f:
    raw = f.read()
  src = raw.decode("utf-8")
  tree = ast.parse(src, filename=path)

  parent: dict[ast.AST, ast.AST] = {}
  for n in ast.walk(tree):
    for c in ast.iter_child_nodes(n):
      parent[c] = n

  fstrings: list[ast.JoinedStr] = []
  for n in ast.walk(tree):
    if isinstance(n, ast.JoinedStr) and any(
      isinstance(v, ast.Constant) and isinstance(v.value, str) and _has_cn(v.value)
      for v in n.values
    ):
      fstrings.append(n)
  # 嵌套 f-string 只取最外层
  outer = [n for n in fstrings if not isinstance(parent.get(n), ast.JoinedStr)]

  inside: set[int] = set()
  for n in outer:
    for sub in ast.walk(n):
      inside.add(id(sub))

  edits: list[tuple[int, int, str, str]] = []  # start, end, new_text, original
  for n in outer:
    new = _rebuild_fstring(n)
    st = _byte_offset(raw, n.lineno, n.col_offset)
    en = _byte_offset(raw, n.end_lineno, n.end_col_offset)
    edits.append((st, en, new, raw[st:en].decode("utf-8")))

  for n in ast.walk(tree):
    if id(n) in inside:
      continue
    if not (isinstance(n, ast.Constant) and isinstance(n.value, str) and _has_cn(n.value)):
      continue
    new = repr(_map_const(n.value, False))
    st = _byte_offset(raw, n.lineno, n.col_offset)
    en = _byte_offset(raw, n.end_lineno, n.end_col_offset)
    edits.append((st, en, new, raw[st:en].decode("utf-8")))

  if not edits:
    return 0, []

  out = raw
  for st, en, new, _ in sorted(edits, reverse=True):
    out = out[:st] + new.encode("utf-8") + out[en:]

  new_src = out.decode("utf-8")
  ast.parse(new_src, filename=path)  # 语法必须仍然合法
  remain = [
    (n.lineno, n.value) for n in ast.walk(ast.parse(new_src))
    if isinstance(n, ast.Constant) and isinstance(n.value, str) and _has_cn(n.value)
  ]
  if remain:
    raise RuntimeError(f"{path} 替换后仍有中文常量: {remain[:5]}")

  samples = [f"{orig[:48]}  ->  {new[:48]}" for _, _, new, orig in sorted(edits)[:4]]
  if apply:
    with open(path, "wb") as f:
      f.write(out)
  return len(edits), samples


def _byte_offset(raw: bytes, lineno: int, col: int) -> int:
  """ast 的 col_offset 是 UTF-8 字节偏移，不是字符偏移。"""
  lines = raw.split(b"\n")
  return sum(len(l) + 1 for l in lines[: lineno - 1]) + col


def check_po() -> list[str]:
  problems = []
  for lang in PO_LANGS:
    po = os.path.join(BASEDIR, TRANSLATIONS_DIR, f"app_{lang}.po")
    if not os.path.exists(po):
      problems.append(f"缺少 {po}")
      continue
    import re
    content = open(po, encoding="utf-8").read()
    existing: dict[str, str] = {}
    for m in re.finditer(r'msgid "((?:[^"\\]|\\.)*)"\nmsgstr "((?:[^"\\]|\\.)*)"', content):
      def unesc(s: str) -> str:
        return s.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
      existing.setdefault(unesc(m.group(1)), unesc(m.group(2)))
    for mid, want in po_entries():
      if mid not in existing:
        problems.append(f"{lang}: 缺少 msgid {mid!r}")
      elif existing[mid] != want:
        problems.append(f"{lang}: {mid!r} 译文 {existing[mid]!r} != {want!r}")
  return problems


def run_check() -> list[str]:
  """供 --check 与 merge_regression_check.py 的 A19 共用的门禁。"""
  problems = []
  for rel in EVENTS_FILES:
    path = os.path.join(BASEDIR, rel)
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    parents: dict[ast.AST, ast.AST] = {}
    for n in ast.walk(tree):
      for c in ast.iter_child_nodes(n):
        parents[c] = n
    for n in ast.walk(tree):
      if (isinstance(n, ast.Constant) and isinstance(n.value, str) and _has_cn(n.value)
          and not isinstance(parents.get(n), ast.Expr)):
        problems.append(f"{rel}:{n.lineno} 硬编码中文 {n.value[:30]!r}")
  problems += check_po()
  return problems


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--check", action="store_true", help="只校验不改文件")
  ap.add_argument("--no-po", action="store_true", help="只改源码，不回填 po")
  args = ap.parse_args()

  if args.check:
    problems = run_check()
    if problems:
      print(f"❌ i18n 校验失败，{len(problems)} 项：")
      for p in problems[:20]:
        print("  " + p)
      return 1
    print("✅ events 源码无硬编码中文，中文 po 覆盖完整")
    return 0

  total = 0
  for rel in EVENTS_FILES:
    path = os.path.join(BASEDIR, rel)
    n, samples = transform(path, True)
    total += n
    print(f"  {rel}: 替换 {n} 处")
    for s in samples:
      print("      " + s)

  if not args.no_po:
    for lang in PO_LANGS:
      po = os.path.join(BASEDIR, TRANSLATIONS_DIR, f"app_{lang}.po")
      added, filled = inject_po(po, lang)
      print(f"  app_{lang}.po: 新增 {added} 条，补译文 {filled} 条")

  problems = check_po()
  print(f"✅ 共替换 {total} 处；中文 po 覆盖 {'完整' if not problems else '不完整'}")
  for p in problems[:10]:
    print("  " + p)
  return 1 if problems else 0


if __name__ == "__main__":
  sys.exit(main())
