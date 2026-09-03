#!/usr/bin/env python3
"""UDS诊断流量分析（2026-09-02）：扫 rlog 里 0x18DAxxxx/0x18DBxxxx CAN-FD 诊断帧
用途: 诊断仪(X431等)插OBD操作ACC模块时, comma录像 → 本脚本分析:
  - 哪些ECU地址被访问(实锤ACC诊断地址)
  - 用了哪些UDS服务/DID(暴露模块诊断能力)
  - 有没有 0x27 seed-key 交换(逆向VAG算法种子数据)
  - 会话切换是否导致 ACC_02 停发(鸡生蛋验证)
用法: python3 ai/tools/scan_uds.py [rlog或段目录, 默认最后一个route]
只读分析, 不发送任何诊断帧。
"""
import glob, sys, os
from collections import defaultdict
from openpilot.tools.lib.logreader import LogReader

def svc_name(b):
  return {0x10:'10-会话切换',0x22:'22-读DID',0x23:'23-读内存',0x27:'27-安全访问',
          0x2E:'2E-写DID',0x31:'31-例程控制',0x34:'34-请求上传',0x3E:'3E-保活',
          0x7F:'7F-负响应',0x11:'11-复位',0x14:'14-清码',0x19:'19-读DTC'}.get(b, f'{b:02X}-未知')

def main(path):
  acc_stop_at=None; acc_go_at=None; last_acc02=None
  stat=defaultdict(lambda: defaultdict(int))   # id -> svc -> n
  dids=defaultdict(set)                         # ecu -> dids
  seed_pairs=[]; sessions=[]; negeg=defaultdict(int)
  diag=defaultdict(int); n_udsframes=0
  for m in LogReader(path):
    w=m.which()
    if w=='can':
      for c in m.can:
        if c.src!=2: continue
        ID=c.address & 0x1FFFFFFF
        if (ID & 0x1FFFF800)!=0x18DA0000 and (ID & 0x1FFFF800)!=0x18DB0000: continue
        d=c.dat
        if len(d)<3: continue
        n_udsframes+=1
        if ID & 0x1000000:  # 29bit
          target=ID & 0xFF; source=(ID>>8)&0xFF; svc=d[1] if d[0]==0x02 else d[0]
          key=f"{ID:08X}({source:02X}->{target:02X})"
          stat[key][svc_name(svc) if svc!=0x7F else f"7F-{d[2]:02X}"]+=1
          diag[(source,target)]+=1
          if svc==0x22 and len(d)>2: dids[(source,target)].add(f"{d[2]:02X}{d[3]:02X}")
          if svc==0x10 and len(d)>2: sessions.append((target, d[2], d[3] if len(d)>3 else 0))
          if svc==0x27:
            seed_pairs.append(('req',source,target,d[2],d[3:].hex()))
          if svc==0x7F: negeg[f"{source:02X}/{d[2]:02X}/{d[3]:02X}"]+=1
        else:
          stat[f"{ID:03X}(标准)"] [svc_name(d[1]) if d[0]==0x02 else svc_name(d[0])]+=1
    elif w=='carState': pass
  print(f"=== UDS帧总数: {n_udsframes} ===")
  print("\n--- 诊断流量统计(ECU地址×服务) ---")
  for k in sorted(stat):
    s=', '.join(f"{sv}:{n}" for sv,n in sorted(stat[k].items()))
    print(f"  {k}: {s}")
  if dids:
    print("\n--- 读过的DID ---")
    for k in sorted(dids): print(f"  {k[0]:02X}->{k[1]:02X}: {sorted(dids[k])}")
  if sessions:
    print("\n--- 会话切换(目标,会话号) ---")
    for s in sessions: print(f"  ECU{s[0]:02X}: 0x10 {s[1]:02X} sub={s[2]:02X}")
  if seed_pairs:
    print(f"\n--- 0x27安全访问帧({len(seed_pairs)}条) ---")
    for sp in seed_pairs: print(f"  {sp[0]} {sp[1]:02X}->{sp[2]:02X} sub={sp[3]:02X} data={sp[4]}")
  if negeg:
    print("\n--- 负响应 ---")
    for k,v in negeg.items(): print(f"  {k}: x{v}")

if __name__=='__main__':
  p=sys.argv[1] if len(sys.argv)>1 else None
  if not p or p.endswith('/'):
    rs=sorted(glob.glob('/data/media/0/realdata/*/'))
    p=rs[-1] if not p else max(glob.glob('/data/media/0/realdata/'+p+'*/'))
    seg=sorted(glob.glob(p+'rlog*'))
    p=seg[0] if seg else p
  if os.path.isdir(p):
    segs=sorted(glob.glob(os.path.join(p,'rlog*')))
    print(f"扫描段: {os.path.basename(os.path.dirname(p))} 共{len(segs)}段")
    for s in segs[:12]: main(s)
  else:
    main(p)
