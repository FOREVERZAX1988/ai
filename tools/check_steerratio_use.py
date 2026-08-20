#!/usr/bin/env python3
"""核实：①4f 路试 carParams 的 steerRatio 实际值 ②动态转向比(steerRatioV2)在哪被消费"""
import glob, sys, os
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

# ---------- 1. 4f carParams 实际值 ----------
segs = sorted(glob.glob("/data/media/0/realdata/0000004f--*/rlog.zst"))
lr = LogReader(segs[0])
for msg in lr:
    w = msg.which()
    if w == "carParams":
        cp = msg.carParams
        print(f"4f carParams.steerRatio = {cp.steerRatio}")
        print(f"carParams.steerRatioV2 字段存在: {hasattr(cp, 'steerRatioV2')}")
        if hasattr(cp, 'steerRatioV2'):
            print(f"  steerRatioV2 = {list(cp.steerRatioV2)}")
        # 找 sp 扩展
        try:
            for f in dir(cp):
                if "teer" in f.lower():
                    print(f"  carParams.{f} = {getattr(cp, f)}")
        except Exception as e:
            print(f"dir err: {e}")
        break
del lr

# 尝试 carParamsSP
try:
    lr = LogReader(segs[0])
    for msg in lr:
        if msg.which() == "carParamsSP":
            sp = msg.carParamsSP
            print(f"\ncarParamsSP 字段（含teer/ratio）:")
            for f in dir(sp):
                if "teer" in f.lower() or "ratio" in f.lower():
                    try:
                        print(f"  {f} = {getattr(sp, f)}")
                    except Exception:
                        pass
            break
    del lr
except Exception as e:
    print(f"carParamsSP err: {e}")

# ---------- 2. steerRatioV2 消费点 ----------
print("\n=== steerRatioV2 消费点 ===")
for base in ["openpilot/selfdrive", "opendbc_repo/opendbc"]:
    for root, dirs, files in os.walk(base):
        for fn in files:
            if fn.endswith(".py"):
                p = f"{root}/{fn}"
                try:
                    s = open(p, encoding="utf-8").read()
                except Exception:
                    continue
                if "teerRatioV2" in s or "teer_ratio_v2" in s:
                    print(f"  {p}")
                    for i, line in enumerate(s.split("\n"), 1):
                        if "teerRatioV2" in line or "teer_ratio_v2" in line:
                            print(f"    L{i}: {line.strip()[:110]}")

# ---------- 3. latcontrol 用哪个算曲率 ----------
print("\n=== latcontrol 转向比使用（曲率计算） ===")
import subprocess
for p in ["openpilot/selfdrive/controls/lib/latcontrol_torque.py",
          "openpilot/selfdrive/controls/lib/latcontrol_pid.py"]:
    try:
        s = open(p, encoding="utf-8").read()
        for i, line in enumerate(s.split("\n"), 1):
            if "teerRatio" in line and ("curv" in line or "steerAngle" in line or "def " in line):
                print(f"  {p} L{i}: {line.strip()[:110]}")
    except Exception as e:
        print(f"  {p}: {e}")
