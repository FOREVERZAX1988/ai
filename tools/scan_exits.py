#!/usr/bin/env python3
"""扫route的enabled降沿(纵向退出点)+alertText原因分类"""
import glob, sys
from openpilot.tools.lib.logreader import LogReader

prefix = sys.argv[1] if len(sys.argv)>1 else '00000070'
fs = sorted(glob.glob(f'/data/media/0/realdata/{prefix}--*/qlog.zst'), key=lambda f:int(f.split('--')[-1].split('/')[0]))
print(f"route {prefix}: {len(fs)}段")
t0 = None
for f in fs:
    seg = f.split('--')[-1].split('/')[0]
    en_prev = False; last_alert = ''; vego = 0; gas = 0; brk = 0; exits = []
    for m in LogReader(f):
        t = m.logMonoTime/1e9
        if t0 is None: t0 = t
        tt = t - t0
        w = m.which()
        try:
            if w == 'carState':
                cs = m.carState
                vego = cs.vEgo; gas = int(cs.gasPressed); brk = int(cs.brakePressed)
            elif w == 'carControl':
                en = bool(m.carControl.enabled)
                if en_prev and not en:
                    exits.append((tt, vego, gas, brk, last_alert))
                en_prev = en
            elif w == 'selfdriveState':
                a = str(m.selfdriveState.alertText1)[:60]
                if a:
                    last_alert = a
        except Exception: pass
    for t, v, g, b, al in exits:
        tag = ''
        if g: tag = '踩油门'
        elif b: tag = '踩刹车(用户)'
        elif al: tag = f'事件: {al}'
        else: tag = '??无事件无介入'
        print(f"seg{seg} t={t:.1f}s vEgo={v*3.6:.1f}km/h [{tag}]")
