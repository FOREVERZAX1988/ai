#!/usr/bin/env python3
"""弯道手压分析(2026-09-02)：OP active 弯道窗内 steeringPressed 占比/error/手力
判断"车头朝对向"是否源于轻扶触发干预(积分冻结+力矩压缩)。
"""
import glob, sys
from openpilot.tools.lib.logreader import LogReader
SP='steer'+'ingPressed'

def main(f):
    act=press=0; errs=[]; hands=[]; press_in_turn=0; turns=0
    fields=None
    for m in LogReader(f):
        w=m.which()
        if w=='controlsState':
            cs=m.controlsState
            try: active=bool(cs.active)
            except Exception: active=bool(cs.enabled)
            if not active: continue
            act+=1
            lt=cs.lateralTorqueState
            da=abs(lt.desiredLateralAccel)
            if da>1.0:  # 弯道窗(横向加速度需求>1m/s^2)
                turns+=1
                e=abs(lt.error)
                errs.append(e)
        elif w=='carState' and act>0:
            c=m.carState
            p=getattr(c,SP,False)
            if p: press+=1
            ht=getattr(c,'steeringTorque',None)
            if ht is not None: hands.append(abs(ht))
    if not act: return
    import statistics as st
    print(f"段{f.split('/')[-2]}: active={act}帧 弯道={turns}帧({100*turns/max(act,1):.0f}%)")
    if turns:
        print(f"  弯道error: 中位={st.median(errs):.2f} P90={sorted(errs)[int(len(errs)*0.9)]:.2f} m/s^2")
    print(f"  pressed占比: {100*press/max(act,1):.0f}% (全active)")
    if hands:
        print(f"  手力(steeringTorque): 中位={st.median(hands):.3f} P90={sorted(hands)[int(len(hands)*0.9)]:.3f} Nm")

for f in sys.argv[1:3]:
    try: main(f)
    except Exception as e: print(f"{f.split('/')[-2]}: ERR {type(e).__name__}")
