#!/usr/bin/env python3
"""验证：用当前代码（含2031c4f）生成 carParams，看 steerRatioV2 是否真的能序列化传递"""
import sys, glob
sys.path.insert(0, "/data/openpilot")
sys.path.insert(0, "/data/openpilot/opendbc_repo")

# 从 4f 拿 fingerprint
from openpilot.tools.lib.logreader import LogReader
segs = sorted(glob.glob("/data/media/0/realdata/0000004f--*/rlog.zst"))
fp = None
lr = LogReader(segs[0])
for msg in lr:
    if msg.which() == "carParams":
        fp = msg.carParams.carFingerprint
        print(f"4f fingerprint: {fp}")
        break
del lr

# 用当前代码生成 carParams
try:
    from opendbc.car.volkswagen.interface import CarInterface
    from opendbc.car import structs
    # 构造 fingerprint dict（simplified）
    # 直接调 _get_params 需要完整环境——改用轻量方式：检查 interface 代码里 steerRatioV2 赋值后 capnp 是否保留
    # 直接实例化测试：用 CarInterface.get_params(fp) 风格
    import inspect
    src = inspect.getsource(CarInterface)
    print("\ninterface 里 steerRatioV2 设置代码存在:", "steerRatioV2" in src)
except Exception as e:
    print(f"import err: {e}")

# 用 capnp 直接验证：structs.CarParams 能否容纳 steerRatioV2
try:
    cp = structs.CarParams()
    print("\nstructs.CarParams 默认 steerRatioV2:", list(cp.steerRatioV2))
    cp.steerRatioV2 = [0.0, 140.0, 145.0, 200.0, 15.0, 15.0, 18.7, 18.7]
    # 序列化→反序列化
    buf = cp.to_bytes()
    cp2 = structs.CarParams.from_bytes(buf)
    v2 = list(cp2.steerRatioV2)
    print(f"写入后序列化再读回: {v2}")
    print(f"steerRatio 读回: {cp2.steerRatio}")
    print("→ 结论:", "steerRatioV2 可正常传递 ✓" if v2 == [0.0,140.0,145.0,200.0,15.0,15.0,18.7,18.7] else "⚠️ steerRatioV2 序列化丢失!")
except Exception as e:
    print(f"capnp 测试 err: {e}")

# 4f 的 carParams 里 steerRatioV2 为什么空——对比 capnp 版本
print("\n=== car.capnp CarParams 中 steerRatioV2 ordinal ===")
try:
    s = open("openpilot/cereal/car.capnp", encoding="utf-8").read()
    for i, line in enumerate(s.split("\n"), 1):
        if "steerRatioV2" in line or "steerRatio" in line:
            print(f"  L{i}: {line.strip()}")
except Exception as e:
    print(f"capnp err: {e}")
