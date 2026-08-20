#!/usr/bin/env python3
"""只读：panda safety 里 VW 的横向力矩/速率限制（MAX_RATE_UP/DOWN 等）"""
import re

# 找 VW 相关 safety 文件
for f in ["/data/openpilot/opendbc_repo/opendbc/safety/modes/volkswagen_common.h",
          "/data/openpilot/opendbc_repo/opendbc/safety/modes/volkswagen_mlb.h"]:
    try:
        s = open(f, encoding="utf-8").read()
    except Exception as e:
        print(f"{f}: {e}")
        continue
    print(f"=== {f} ===")
    # 横向力矩限制相关
    for pat in ["MAX_RATE", "MAX_TORQUE", "torque", "rate", "lateral"]:
        for m in re.finditer(rf".*{pat}.*", s):
            line = m.group(0).strip()
            if line and not line.startswith("// *"):
                print(f"  {line[:120]}")
    print()
