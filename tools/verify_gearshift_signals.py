#!/usr/bin/env python3
"""验证档位/转速信号能否从rlog解析。打印原始值分布。"""
import sys, glob, os
from collections import Counter
ROUTE = sys.argv[1] if len(sys.argv)>1 else "00000071--363798636e--0"
BASE='/data/media/0/realdata'
def be(data, byte): return data[byte] if byte < len(data) else -1
def bit(data, start, length):
  v=0
  for i in range(length):
    byte=(start+i)//8; bitp=(start+i)%8
    if byte>=len(data): return -1
    v |= ((data[byte]>>bitp)&1)<<i
  return v
f=f'{BASE}/{ROUTE}/rlog.zst'
from openpilot.tools.lib.logreader import LogReader
gear_c=Counter(); ist_c=Counter(); rpm_vals=[]; N=0
for m in LogReader(f):
  if m.which()!='can': continue
  for c in m.can:
    d=c.dat
    if c.address==129 and len(d)>=8:
      g=bit(d,49,4); gear_c[g]+=1; N+=1
    elif c.address==263 and len(d)>=8:
      g=bit(d,8,4); ist_c[g]+=1
    elif c.address==128 and len(d)>=4:
      rpm=bit(d,16,16)*0.25; rpm_vals.append(rpm)
print(f'total 129 seen: {N}')
print('Motor_02 Gangposition分布:', dict(gear_c))
print('Motor_04 Istgang分布:', dict(ist_c))
if rpm_vals:
  import statistics
  print(f'rpm样本{len(rpm_vals)}  min{min(rpm_vals):.0f} max{max(rpm_vals):.0f} mean{statistics.mean(rpm_vals):.0f}')
