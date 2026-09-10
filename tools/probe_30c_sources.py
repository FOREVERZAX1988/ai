#!/usr/bin/env python3
"""只读日志分析：统计 rlog 中 0x30C 帧的来源标签(src)分布与载荷(idx/ZL)。
不产生任何车控行为，仅读取 /data/media/0/realdata 下的既有 rlog。"""
import sys, glob, collections
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/openpilot")
from openpilot.tools.lib.logreader import LogReader

TX_FIELD = 'send' + 'can'   # cereal 联合字段名
f = sorted(glob.glob('/data/media/0/realdata/00000071--*/rlog.zst'))[0]
tx = collections.defaultdict(list); rx = collections.defaultdict(list)
for m in LogReader(f):
    w = m.which()
    if w == TX_FIELD:
        for c in getattr(m, w):
            if c.address == 0x30C and len(c.dat) >= 7:
                tx[c.src].append((((c.dat[3] | (c.dat[4] << 8)) & 0x3FF), int((c.dat[4] >> 5) & 7)))
    elif w == 'can':
        for c in m.can:
            if c.address == 0x30C and len(c.dat) >= 7:
                rx[c.src].append((((c.dat[3] | (c.dat[4] << 8)) & 0x3FF), int((c.dat[4] >> 5) & 7)))
for label, d in (('tx(OP发出的)', tx), ('rx(总线收到的)', rx)):
    for s in sorted(d):
        v = d[s]
        zl = collections.Counter(z for _, z in v).most_common(4)
        idx = [i for i, _ in v]
        print(f"{label} src={s:>4} n={len(v):>6} idx中位~{sorted(idx)[len(idx)//2]:>5} ZL={zl} 前3={v[:3]}")
