#!/usr/bin/env python3
"""对已插入的坏块（条目间缺空行）再跑一次空行修复，然后验证新开关3条可查"""
import sys

PO_FILES = [
    "openpilot/selfdrive/ui/translations/app_zh-CHS.po",
    "openpilot/selfdrive/ui/translations/app_zh-CHT.po",
]

for pf in PO_FILES:
    lines = open(pf, encoding="utf-8").read().split("\n")
    out = []
    seen_msgstr = False
    fixed = 0
    for line in lines:
        s = line.strip()
        if not s:
            seen_msgstr = False
            out.append(line)
            continue
        if s.startswith("#"):
            out.append(line)
            continue
        if s.startswith("msgid "):
            if seen_msgstr:
                out.append("")
                fixed += 1
                seen_msgstr = False
            out.append(line)
            continue
        if s.startswith("msgstr"):
            seen_msgstr = True
            out.append(line)
            continue
        out.append(line)
    open(pf, "w", encoding="utf-8").write("\n".join(out))
    print(f"{pf.split('/')[-1]}: 再修复 {fixed} 处")

sys.path.insert(0, "/data/openpilot")
from openpilot.system.ui.lib.multilang import load_translations
from pathlib import Path

DESC = ("Dynamic Steering Ratio (Macan): speed-dependent steering ratio - 15.0 below 140 km/h, "
        "18.7 above 145 km/h (linear transition 140-145), fitted from 29,284 samples across "
        "the full 4f route (RMSE 1.75 deg), plus torque friction 0.52. When disabled, uses "
        "stock fixed 16.2. Replaces the old experimental 18.0 (discarded: 22% gyro spread, "
        "15% oversteer in city corners).")

all_ok = True
for pf in PO_FILES:
    fn = pf.split("/")[-1]
    trs, plur = load_translations(Path(pf))
    keys = ["Dynamic Steering Ratio (Macan)", DESC, "Macan Dynamic Steering Ratio"]
    ok = all(k in trs for k in keys)
    all_ok &= ok
    print(f"{fn}: 总条目={len(trs)} | 新开关3条={'✅' if ok else '❌'}")
    if ok:
        for k in keys:
            print(f"    {k[:40]}... → {trs[k][:25]}...")
print("\n✅ 全部通过" if all_ok else "❌ 仍有失败")
