#!/usr/bin/env python3
"""_probe_sng_timeline.py <rlog.zst> <lo> <hi>

逐帧（只在值变化时打印）时间线，用于 SnG / st=6 事件复盘。
lo/hi 为 logMonoTime 秒（本机 rlog 每个 seg 文件是"从 route 首帧起累积"的，
route 91 首帧 t≈108.5s，故 route 内相对时间 = t - 108.5）。

打印：
  ACC_05 S5 = 原厂(bus2, src2)   ACC_05 O5 = OP 代发(bus0/128)
  ACC_02 S2 = 原厂   ACC_02 O2 = OP 代发
      ACC_05 字段: (st, vz, mom, anh, loese, esp)   st=ACC_Status_ACC(57|3@1)
      ACC_02 字段: (abstandsindex, rel(bit46,3b), prio(bit44,2b), wunschgeschw(bit12,10b), prim_anz(bit22,2b))
        rel&3==1 表示"Relevantes_Objekt"，wunschgeschw*0.32 = km/h（1022 = 失效）
  CS  = carState(v, standstill, gas, brake, cruise.enabled, cruise.speed[m/s], accFaulted)
  RD  = radarState.leadOne (present, dRel, vRel)
  SD  = selfdriveState (enabled, state)      CX = controlsState.longControlState
  CC  = carControl.actuators.accel / longActive / enabled

注意：ACC_Status_ACC 是 57|3@1+（小端），正确解码 = (byte7 >> 1) & 7。
老工具 ai/tools/scan_st6_*.py 用的 MSB-first extract(d,57,3) 对该信号是错的（会
打印出不存在的 st=7），已由 openpilot CANParser(vw_mlb, bus=2) 校验。
"""
import sys
sys.path.insert(0, '/data/openpilot')
from openpilot.tools.lib.logreader import LogReader


def g(x, s, n):
    return (int.from_bytes(x, 'little') >> s) & ((1 << n) - 1)


lo, hi, path = float(sys.argv[2]), float(sys.argv[3]), sys.argv[1]
prev = {}
first = last = None

for e in LogReader(path):
    t = e.logMonoTime / 1e9
    if first is None:
        first = t
    last = t
    if t < lo or t > hi:
        continue
    w = e.which()
    if w == 'can':
        for m in e.can:
            x = bytes(m.dat)
            if m.address == 269:
                row = ('ACC_05', 'S5' if m.src == 2 else 'O5',
                       g(x, 57, 3), round(g(x, 32, 11) * 0.005 - 7.22, 2), g(x, 16, 10),
                       g(x, 62, 1), g(x, 43, 1), g(x, 61, 1))
            elif m.address == 780:
                row = ('ACC_02', 'S2' if m.src == 2 else 'O2',
                       g(x, 24, 10), g(x, 46, 3) & 3, g(x, 44, 2), g(x, 12, 10), g(x, 22, 2))
            else:
                continue
            k, v = (row[0], row[1]), row[2:]
            if prev.get(k) != v:
                prev[k] = v
                print(f"{t:8.2f} {k[0]} {k[1]} {v}", flush=True)
    elif w == 'carState':
        cs = e.carState
        row = (round(cs.vEgo, 1), int(cs.standstill), int(cs.gasPressed), int(cs.brakePressed),
               int(cs.cruiseState.enabled), round(cs.cruiseState.speed, 1), int(cs.accFaulted))
        if prev.get(('CS',)) != row:
            prev[('CS',)] = row
            print(f"{t:8.2f} CS v={row[0]:5.1f} std={row[1]} gas={row[2]} brk={row[3]} "
                  f"en={row[4]} set={row[5]:5.1f} fault={row[6]}", flush=True)
    elif w == 'radarState':
        l1 = e.radarState.leadOne
        row = (int(l1.present), round(l1.dRel, 1), round(l1.vRel, 1), int(l1.radar))
        if prev.get(('RD',)) != row:
            prev[('RD',)] = row
            print(f"{t:8.2f} RD lead={row[0]} dRel={row[1]:6.1f} vRel={row[2]:6.1f} radar={row[3]}", flush=True)
    elif w == 'selfdriveState':
        row = (int(e.selfdriveState.enabled), e.selfdriveState.state)
        if prev.get(('SD',)) != row:
            prev[('SD',)] = row
            print(f"{t:8.2f} SD enabled={row[0]} state={row[1]}", flush=True)
    elif w == 'controlsState':
        row = (e.controlsState.longControlState,)
        if prev.get(('CX',)) != row:
            prev[('CX',)] = row
            print(f"{t:8.2f} CX longCtrl={row[0]}", flush=True)
    elif w == 'carControl':
        a = e.carControl.actuators
        row = (round(a.accel, 2), int(e.carControl.longActive), int(e.carControl.enabled))
        if prev.get(('CC',)) != row:
            prev[('CC',)] = row
            print(f"{t:8.2f} CC accel={row[0]:6.2f} longActive={row[1]} enabled={row[2]}", flush=True)

print(f"\n[file {path}] first={first:.2f} last={last:.2f}")
