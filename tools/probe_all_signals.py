#!/usr/bin/env python3
"""Macan/MLB 原厂信号综合扫描 v3（性能优化版）
- 预建 address→signal 映射（O(1) 查表，替代逐信号循环）
- 每 route 扫前 2 段 × 12000 帧
- 输出统计表到 stdout + 文件"""
import re, glob, sys, os
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
import numpy as np

DBC = "opendbc_repo/opendbc/dbc/vw_mlb.dbc"
text = open(DBC, encoding="latin-1").read()

SIG_LIST = [
  ("TSK_Steigung", "变速箱坡度%"),
  ("TSK_QBit_Steigung", "坡度有效位"),
  ("PSD_Endsteigung", "换挡坡度%"),
  ("ESP_Laengsbeschl", "ESP纵向加速度m/s2"),
  ("ESP_Querbeschleunigung", "ESP横向加速度g"),
  ("ESP_Gierrate", "ESP横摆角速度"),
  ("ESP_VZ_Gierrate", "横摆角速度符号"),
  ("ACC_Status_ACC", "ACC状态3/4/2/6"),
  ("ACC_Momentenanforderung", "ACC力矩请求"),
  ("ACC_Verz_anf", "ACC减速请求"),
  ("ACC_Anhalten", "停车保持请求"),
  ("ACC_Freigabe_Momentenanf", "力矩通道使能"),
  ("ACC_Freigabe_Verzanf", "减速通道使能"),
  ("ACC_Sollbeschleunigung", "目标加速度"),
  ("ACC_neg_Sollbeschl_Grad", "负加速度梯度"),
  ("ACC_pos_Sollbeschl_Grad", "正加速度梯度"),
  ("ACC_Gesetzte_Zeitluecke", "车距档位"),
  ("EPS_Lenkmoment", "EPS转向扭矩0.01Nm"),
  ("HCA_Anforderung", "HCA扭矩请求"),
  ("TSK_Status", "巡航状态"),
]

def sig_def(name):
    m = re.search(rf'^ SG_ {name} : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)', text, re.M)
    if not m:
        return None
    start, length, signed = int(m.group(1)), int(m.group(2)), m.group(4) == '-'
    scale, offset = float(m.group(5)), float(m.group(6))
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if f'SG_ {name} ' in ln:
            for j in range(i, -1, -1):
                bm = re.match(r'^BO_ (\d+) (\w+)', lines[j])
                if bm:
                    return int(bm.group(1)), bm.group(2), start, length, signed, scale, offset
    return None

def get_sig(dat, start, length, signed):
    val = 0
    for i in range(length):
        byte = (start + i) // 8
        bit = (start + i) % 8
        if dat[byte] & (1 << bit):
            val |= (1 << i)
    if signed and val & (1 << (length - 1)):
        val -= (1 << length)
    return val

# 提取位定义 + 建地址映射
defs = {}
addr_map = {}
for name, desc in SIG_LIST:
    d = sig_def(name)
    if d:
        defs[name] = d
        addr_map.setdefault(d[0], []).append((name, d))
        print(f"✅ {name}: BO_{d[0]} {d[1]} start={d[2]} len={d[3]} scale={d[5]:g} offset={d[6]:g} [{desc}]")
    else:
        print(f"❌ {name}: dbc 未找到")

# 收集 routes（扁平 + 段目录）
flat = sorted(glob.glob("/data/media/0/realdata/*--*--rlog.zst"))
dirs = sorted(glob.glob("/data/media/0/realdata/*/rlog.zst"))
routes = {}
for p in flat + dirs:
    base = os.path.basename(p).split("--")[0]
    routes.setdefault(base, []).append(p)
print(f"\n共 {len(routes)} 个 route: {sorted(routes.keys())}")
print(f"rlog 总数: {len(flat)+len(dirs)}")

# 扫描（O(1) 查表）
results = {name: {} for name in defs}
for route in sorted(routes):
    for p in routes[route][:2]:  # 每 route 前 2 段
        try:
            lr = LogReader(p)
        except Exception:
            continue
        n = 0
        for msg in lr:
            n += 1
            if n > 12000:
                break
            if msg.which() == "can":
                for c in msg.can:
                    for name, (bid, bname, start, length, signed, scale, offset) in addr_map.get(c.address, []):
                        results[name].setdefault(route, []).append(
                            get_sig(bytes(c.dat), start, length, signed) * scale + offset)
        del lr

# 输出
out = []
out.append(f"\n{'信号':<26}{'route':<10}{'n':>6}{'min':>9}{'max':>9}{'中位':>8}{'非零%':>6}")
for name, desc in SIG_LIST:
    if name not in defs:
        continue
    for route in sorted(routes):
        vals = results[name].get(route)
        if not vals:
            continue
        a = np.array(vals)
        nz = np.sum(a != 0) / len(a) * 100
        line = f"{name:<26}{route:<10}{len(a):>6}{a.min():>9.3f}{a.max():>9.3f}{np.median(a):>8.3f}{nz:>6.0f}"
        out.append(line)
        print(line)
out.append("\n扫描完成")
with open("/data/openpilot/ai/tools/signal_scan_output.txt", "w") as f:
    f.write("\n".join(out))
print("\n已保存 signal_scan_output.txt")
