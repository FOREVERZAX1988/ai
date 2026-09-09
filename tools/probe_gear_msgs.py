#!/usr/bin/env python3
"""探测Macan rlog里哪些can报文含换挡/转速信息。dump候选报文原始变化。"""
import sys, os
from collections import defaultdict
ROUTE = sys.argv[1] if len(sys.argv)>1 else "00000071--363798636e--0"
f=f'/data/media/0/realdata/{ROUTE}/rlog.zst'
from openpilot.tools.lib.logreader import LogReader
# 记录每个address: (count, 采样byte值变化集合)
addr_samples=defaultdict(lambda:[0,set()])
gear_addr_candidates=[129,263,130,131,258,1089,1414,490,1730,2017,2025,1981]
for m in LogReader(f):
  if m.which()!='can': continue
  for c in m.can:
    addr_samples[c.address][0]+=1
# 打印变速箱ECU相关报文的byte分布
print("=== 变速箱相关报文 各byte取值变化(有变化才有换挡信息) ===")
for a in sorted(addr_samples):
  if a in gear_addr_candidates:
    # 只展示，实际值在下一步
    pass
# 专门dump候选地址的byte1/byte2(位8-23, 含Istgang bit8-11)
for a in gear_addr_candidates:
  n=addr_samples[a][0]
  if n==0: continue
  # 重新扫，收集位8-23(byte1-2)的4bit组分布
  print(f'\n--- address {a} (帧数{n}) byte1,byte2 变化 ---', flush=True)
  seen=set(); 
  cnt=0
  for m in LogReader(f):
    if m.which()!='can': continue
    for c in m.can:
      if c.address==a and len(c.dat)>=4:
        b1=c.dat[1]&0xF; b2=(c.dat[1]>>4); b3=c.dat[2]&0xF
        seen.add((b1,b2,b3)); cnt+=1
        if len(seen)>12: break
    if len(seen)>12: break
  for v in sorted(seen): print(f'   byte1低4bit={v[0]} byte1高4bit={v[1]} byte2低4bit={v[2]}')
