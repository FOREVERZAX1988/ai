#!/usr/bin/env python3
"""把我方旧版 .po 里已有的翻译补回重新生成的 .po。

背景：本次合并上游把翻译全面重新生成（213 条 relabel、11 种语言重翻），但上游不知道
我们 fork 独有的 UI 字符串（FLM 调参、Carrot 参数等 97 条），重新生成后这些条目
msgstr 全空。以「新文件为准，旧文件只填空缺」的方式补，既拿上游的新翻译，
又不丢自己的中文。

用法：python3 ai/tools/backfill_po.py <old.po> <new.po> [...]
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from openpilot.selfdrive.ui.translations.potools import parse_po, write_po


def load_from_git(rev: str, path: str) -> str:
  return subprocess.run(["git", "show", f"{rev}:{path}"], check=True,
                        capture_output=True, text=True).stdout


def main() -> int:
  if len(sys.argv) < 3:
    print(__doc__)
    return 2
  old_rev = sys.argv[1]
  new_files = sys.argv[2:]

  for new_path in new_files:
    rel = new_path
    try:
      old_text = load_from_git(old_rev, rel)
    except subprocess.CalledProcessError:
      print(f"skip {rel}: not in {old_rev}")
      continue

    with tempfile.NamedTemporaryFile("w", suffix=".po", delete=False, encoding="utf-8") as f:
      f.write(old_text)
      old_tmp = f.name

    _, old_entries = parse_po(old_tmp)
    old_map = {e.msgid: e for e in old_entries if e.msgid}

    header, new_entries = parse_po(new_path)
    filled = 0
    for e in new_entries:
      if not e.msgid:
        continue
      old = old_map.get(e.msgid)
      if old is None:
        continue
      if e.is_plural:
        if not e.msgstr_plural and old.msgstr_plural:
          e.msgstr_plural = dict(old.msgstr_plural)
          filled += 1
      elif not e.msgstr and old.msgstr:
        e.msgstr = old.msgstr
        filled += 1

    write_po(new_path, header, new_entries)
    print(f"{rel}: 补回 {filled} 条翻译")

  return 0


if __name__ == "__main__":
  raise SystemExit(main())
