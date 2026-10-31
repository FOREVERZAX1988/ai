#!/usr/bin/env python3
"""上游翻错的中文条目，这里强制覆盖。

背景：`app_*.po` 是随上游一起重新生成的，`merge_po` 只在 msgstr 为空时才填。
所以上游一旦把某条中文翻错，我们改对了也会在下次合并时被它覆盖回去
（2026-10-31 实测：`Stop` 在 59d5f19501 是"停止"，合完 da9fe91aee 又变回"停车"）。

每个上游合并之后跑一次即可：
    python3 ai/tools/zh_overrides.py

判据只有一条：**看这条 msgid 在代码里的真实用途**，别照着英文词面翻。
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))
from openpilot.selfdrive.ui.translations.potools import parse_po, write_po

TRANS = BASE / "openpilot/selfdrive/ui/translations"

# {文件: {msgid: 正确译文}}
OVERRIDES = {
  "app_zh-CHS.po": {
    # bluetooth_settings.py:446 — 扫描按钮：正在扫描时显示 Stop（停止扫描）。
    # 上游译成"停车"（parking），语义完全不对。
    "Stop": "停止",
  },
  "app_zh-CHT.po": {
    "Stop": "停止",
  },
}


def main() -> int:
  changed = 0
  for name, table in OVERRIDES.items():
    path = TRANS / name
    if not path.is_file():
      print(f"skip {name}: 文件不存在")
      continue
    header, entries = parse_po(path)
    hits = 0
    for e in entries:
      if e.msgid in table and e.msgstr != table[e.msgid]:
        print(f"  {name}: {e.msgid!r} {e.msgstr!r} -> {table[e.msgid]!r}")
        e.msgstr = table[e.msgid]
        hits += 1
    if hits:
      write_po(path, header, entries)
      changed += hits
    else:
      print(f"  {name}: 已是目标译文")
  print(f"共修正 {changed} 条")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
