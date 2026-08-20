#!/usr/bin/env python3
"""全面核实：'Steering Params (Macan)' 等字符串在 repo 里的所有出现点（.py/.po），确认改没改、哪几处"""
import os

patterns = ["Steering Params (Macan)", "Dynamic Steering Ratio", "Macan Steering Params",
            "Macan Dynamic Steering Ratio", "Auto Lane Change: Delay with Blind"]
exts = (".py", ".po", ".cc", ".h", ".ts", ".qml", ".ui")

hits = {}
for base in ["openpilot", "opendbc_repo/opendbc"]:
    for root, dirs, files in os.walk(base):
        for fn in files:
            if not fn.endswith(exts):
                continue
            p = f"{root}/{fn}"
            try:
                s = open(p, encoding="utf-8").read()
            except Exception:
                continue
            for pat in patterns:
                idx = 0
                while True:
                    i = s.find(pat, idx)
                    if i < 0:
                        break
                    line_no = s.count("\n", 0, i) + 1
                    line = s.split("\n")[line_no - 1].strip()
                    hits.setdefault(pat, []).append(f"{p}:L{line_no}: {line[:100]}")
                    idx = i + 1

for pat in patterns:
    print(f"\n=== '{pat}' ===")
    if pat in hits:
        for h in hits[pat]:
            print(f"  {h}")
    else:
        print("  （无任何出现）")
