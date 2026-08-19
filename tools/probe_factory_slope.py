#!/usr/bin/env python3
"""探测原厂坡度/加速度信号在实车是否可用（Macan/MLB）
信号：TSK_Steigung（变速箱坡度%）、PSD_Endsteigung（坡度%）、ESP_Laengsbeschl（纵向加速度m/s²）、ESP_Querbeschleunigung（横向g）
方法：从 vw_mlb.dbc 提取位定义 → 扫 00000002 route 的 can 帧解析 → 统计值分布/有效性"""
import re, glob, sys
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
import numpy as np

DBC = "opendbc_repo/opendbc/dbc/vw_mlb.dbc"
text = open(DBC, encoding="latin-1").read()

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

names = ["TSK_Steigung", "TSK_QBit_Steigung", "PSD_Endsteigung", "ESP_Laengsbeschl", "ESP_Querbeschleunigung"]
defs = {}
for n in names:
    d = sig_def(n)
    print(f"{n}: {d}")
    if d:
        defs[n] = d

# 扫 00000002（扁平文件 + 段目录两种格式）
paths = sorted(glob.glob("/data/media/0/realdata/00000002--*--rlog.zst"))[:4]
paths += sorted(glob.glob("/data/media/0/realdata/00000002--*/rlog.zst"))[:4]
paths = list(dict.fromkeys(paths))  # 去重
stats = {n: [] for n in defs}
v_ego_samples = []
for p in paths:
    try:
        lr = LogReader(p)
    except Exception:
        continue
    n_msgs = 0
    for msg in lr:
        n_msgs += 1
        if n_msgs > 30000:
            break
        if msg.which() == "carState":
            v_ego_samples.append(msg.carState.vEgo)
        elif msg.which() == "can":
            for c in msg.can:
                for n, (bid, bname, start, length, signed, scale, offset) in defs.items():
                    if c.address == bid:
                        v = get_sig(bytes(c.dat), start, length, signed) * scale + offset
                        stats[n].append(v)
    del lr

print(f"\n扫描段数: {len(paths)}")
for n, vals in stats.items():
    if vals:
        a = np.array(vals)
        print(f"{n}: n={len(a)} 范围[{a.min():.3f},{a.max():.3f}] 中位={np.median(a):.3f} 非零比={np.sum(a!=0)/len(a)*100:.0f}% 有效(QBit/变化)={np.sum(np.abs(np.diff(a[:1000]))>0.01)/max(1,min(999,len(a)-1))*100:.0f}%")
    else:
        print(f"{n}: 无数据（实车未广播或报文未出现在采样段）")
if v_ego_samples:
    print(f"vEgo: n={len(v_ego_samples)} 范围[{min(v_ego_samples):.1f},{max(v_ego_samples):.1f}] km/h")
