#!/usr/bin/env python3
"""异常减速最终定位：段8 53400-54400 / 段12 36000-37200
看 longitudinalPlanSource + shouldStop + vEgo 实际响应 + verzO 执行"""
import glob, sys
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader

segs = sorted(glob.glob("/data/media/0/realdata/0000004f--*/rlog.zst"))

def show(si, lo, hi, label):
    lr = LogReader(segs[si])
    st = {"f": 0, "v": 0.0, "vSet": 0.0, "aTgt": 0.0, "src": "", "stop": False,
          "verzO": 99, "momO": -99, "en": False}
    print(f"\n===== {label} (段{si} 帧{lo}-{hi}) =====")
    print(f"{'帧':>6} {'v':>5} {'vSet':>5} | {'aTgt':>6} {'verzO':>6} {'momO':>5} | {'src':>6} {'stop':>4}")
    for msg in lr:
        f = st["f"]
        if msg.which() == "carState":
            cs = msg.carState
            st["v"] = cs.vEgo
            st["vSet"] = cs.cruiseState.speed * 3.6
            st["en"] = cs.cruiseState.enabled
        elif msg.which() == "longitudinalPlan":
            lp = msg.longitudinalPlan
            st["aTgt"] = lp.aTarget
            try: st["src"] = str(lp.longitudinalPlanSource)
            except Exception: pass
            try: st["stop"] = lp.shouldStop
            except Exception: pass
        elif msg.which() == "can":
            for c in msg.can:
                if c.address == 269 and c.src == 128 and len(c.dat) >= 8:
                    d = bytes(c.dat)
                    vz_raw = 0
                    for i in range(11):
                        byte = (32 + i) // 8
                        bit = (32 + i) % 8
                        if d[byte] & (1 << bit): vz_raw |= (1 << i)
                    st["verzO"] = vz_raw * 0.005 - 7.22
                    mom_raw = 0
                    for i in range(10):
                        byte = (16 + i) // 8
                        bit = (16 + i) % 8
                        if d[byte] & (1 << bit): mom_raw |= (1 << i)
                    st["momO"] = mom_raw
        if lo <= f <= hi and f % 25 == 0:
            print(f"{f:>6} {st['v']*3.6:>5.1f} {st['vSet']:>5.1f} | {st['aTgt']:>6.2f} {st['verzO']:>6.2f} {st['momO']:>5.0f} | {st['src']:>6} {int(st['stop']):>4}")
        st["f"] += 1
        if f > hi: break
    del lr

show(8, 53400, 54400, "段8 减速-恢复全貌")
show(12, 36000, 37200, "段12 减速全貌（含之前状态）")
