#!/usr/bin/env python3
"""L1 参数组合：(hold 时长, 出门 prob 门) -> 车库事件覆盖率 vs 高速暴露面"""
import numpy as np, os
CACHE="/data/openpilot/ai/tools/cache_l1l2_1008"
segs=[f"00000092--d83e53a0c7--{i}" for i in range(1,16)]
R=[]
for s in segs:
    f=f"{CACHE}/{s}.npz"
    if os.path.exists(f):
        z=np.load(f,allow_pickle=True); d={k:z[k] for k in z.files}; d["tr"]=d["t"]-d["t"][0]; d["seg"]=s[-2:]; R.append(d)

def sim(r, hold, gate):
    t=r["t"]; last=-9e9; out=np.zeros(len(t),bool); gaps=[]; cur=None
    for i in range(len(t)):
        if r["lead_present"][i]>0.5: last=t[i]
        alive = (r["lead_present"][i]>0.5) or ((gate<=r["prob"][i]<0.5) and (t[i]-last)<=hold)
        if r["lead_present"][i]>0.5 and t[i]-last>hold: pass
        out[i]=alive and r["lead_present"][i]<0.5   # 仅统计"被 L1 救回"的帧
        if not alive:
            if cur is None: cur=[t[i],t[i]]
            else: cur[1]=t[i]
        else:
            if cur is not None: gaps.append(tuple(cur)); cur=None
    if cur: gaps.append(tuple(cur))
    # 干净重算 last=最近一次 lead_present 帧
    return out, gaps

def sim2(r, hold, gate):
    t=r["t"]; last_conf=-9e9; last_pres=-9e9
    alive=np.zeros(len(t),bool); rescued=np.zeros(len(t),bool)
    for i in range(len(t)):
        pres=r["lead_present"][i]>0.5
        if pres:
            last_pres=t[i]
            if 0.5<=r["prob"][i] or True: pass
            last_conf=t[i]
        hold_ok = (not pres) and (gate<=r["prob"][i]<0.5) and (t[i]-last_conf)<=hold
        alive[i]= pres or hold_ok
        rescued[i]= (not pres) and hold_ok
    return rescued, alive

print(f"{'hold':>5} {'gate':>5} | {'车库窗口覆盖(46.8-48.3)':>22} {'高速(v>10)救回帧':>16} {'低速(<4)救回帧':>14} {'全线救回占比':>12}")
for hold in (0.5,0.8,1.0,1.2):
    for gate in (0.25,0.20):
        cov=0; tot=0; hi=0; lo=0; resc=0; allf=0
        for r in R:
            resc_i,alive=sim2(r,hold,gate)
            resc+=int(resc_i.sum()); allf+=len(r["t"])
            hi+=int((resc_i&(r["vEgo"]>10)).sum()); lo+=int((resc_i&(r["vEgo"]<4)&(r["enabled"]>0.5)).sum())
            if r["seg"]=="-2":
                m=(r["tr"]>=46.8)&(r["tr"]<=48.3)
                cov+=int((alive&m).sum()); tot+=int(m.sum())
        print(f"{hold:>5.1f} {gate:>5.2f} | {cov:>10d}/{tot:<10d}     {hi:>16d} {lo:>14d} {100*resc/allf:>11.2f}%")

print("\n=== 高速(v>10m/s) 被救回帧的『上次已知距离』分布（决定刹车压力）===")
for r in R:
    resc_i,alive=sim2(r,0.5,0.25)
    m=resc_i&(r["vEgo"]>10)
    for i in np.where(m)[0]:
        print(f"  seg{r['seg']} tr={r['tr'][i]:6.1f} v={r['vEgo'][i]:5.1f} prob={r['prob'][i]:.2f} 模型x={r['vis_x'][i]-1.52:6.1f}")
