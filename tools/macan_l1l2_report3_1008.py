#!/usr/bin/env python3
import numpy as np, os
CACHE="/data/openpilot/ai/tools/cache_l1l2_1008"
segs=[f"00000092--d83e53a0c7--{i}" for i in range(1,16)]
R=[]
for s in segs:
    f=f"{CACHE}/{s}.npz"
    if os.path.exists(f):
        z=np.load(f,allow_pickle=True); d={k:z[k] for k in z.files}; d["seg"]=s[-2:]
        d["tr"]=d["t"]-d["t"][0]; R.append(d)

print("===== A) L2 改判帧的<后续 2s 计划>：是提前刹（模型对）还是逆着计划刹（可疑）=====")
fx=[]; neg05=0; neg10=0; neg20=0; tot=0
for r in R:
    fl=(r["enabled"]>0.5)&(r["mdes"]<-0.2)&(np.array([s!="e2e" for s in r["src"]]))&(r["a_plan"]>0.0)
    idx=np.where(fl)[0]
    for i in idx:
        j05=np.searchsorted(r["t"],r["t"][i]+0.5); j10=np.searchsorted(r["t"],r["t"][i]+1.0); j20=np.searchsorted(r["t"],r["t"][i]+2.0)
        if j20>=len(r["t"]): continue
        tot+=1
        a05=np.min(r["a_plan"][i:j05+1]); a10=np.min(r["a_plan"][i:j10+1]); a20=np.min(r["a_plan"][i:j20+1])
        neg05+= a05<0; neg10+= a10<0; neg20+= a20<0
        fx.append((r["a_plan"][i],a10,r["vEgo"][i],r["lead_present"][i]))
fx=np.array(fx)
print(f"样本 {tot} 帧")
print(f"  未来 0.5s 内 MPC 自己也转负: {100*neg05/tot:.0f}%   1s: {100*neg10/tot:.0f}%   2s: {100*neg20/tot:.0f}%")
print(f"  这些帧当前 a_plan 中位 {np.median(fx[:,0]):+.2f}, 未来1s最小 a_plan 中位 {np.median(fx[:,1]):+.2f}")
print(f"  其中 v>10m/s: {int((fx[:,2]>10).sum())} 帧, 无 lead {int(((fx[:,2]>10)&(fx[:,3]<0.5)).sum())} 帧")

print("\n===== B) L1 hold 的距离误差（hold = 上次融合 dRel 以 vEgo 死推）=====")
err=[]
for r in R:
    t=r["t"]; p=r["prob"]; lp=r["lead_present"]
    last_conf=-9e9; last_d=np.nan; last_t=np.nan
    for i in range(len(t)):
        if (r["enabled"][i]<0.5): last_conf=-9e9; continue
        cand = (lp[i]<0.5) and 0.25<=p[i]<0.5 and (t[i]-last_conf)<=0.5
        if cand and np.isfinite(last_d):
            hold=last_d - r["vEgo"][i]*(t[i]-last_t)
            x=r["vis_x"][i]-1.52
            err.append((hold,x,r["vEgo"][i],r["seg"]))
        if lp[i]>0.5 and np.isfinite(r["d_fus"][i]):
            last_d=r["d_fus"][i]; last_t=t[i]; last_conf=t[i]
err=np.array([(e[0],e[1],e[2]) for e in err])
if len(err):
    print(f"样本 {len(err)} 帧")
    print(f"  hold 距离分位(5/50/95): {np.round(np.percentile(err[:,0],[5,50,95]),1)}")
    print(f"  模型当帧 x 分位(5/50/95): {np.round(np.percentile(err[:,1],[5,50,95]),1)}")
    print(f"  |hold - x| 中位 {np.median(np.abs(err[:,0]-err[:,1])):.1f} m, p90 {np.percentile(np.abs(err[:,0]-err[:,1]),90):.1f} m")
    low=err[err[:,2]<4]
    if len(low): print(f"  低速(<4m/s) {len(low)} 帧: hold 中位 {np.median(low[:,0]):.1f} m, 模型x 中位 {np.median(low[:,1]):.1f} m, |Δ| 中位 {np.median(np.abs(low[:,0]-low[:,1])):.1f} m")

print("\n===== C) seg2 (车库) 相对时间逐帧 =====")
r=[x for x in R if x["seg"]=="-2"][0]
i0=int(np.searchsorted(r["tr"],164.0)); i1=int(np.searchsorted(r["tr"],172.0))
print(f"{'tr':>7} {'v':>5} {'prob':>5} {'lead':>5} {'mdes':>6} {'a_plan':>7} {'src':>7}  L1会hold?")
for i in range(i0,min(i1,len(r["t"]))):
    if i%4: continue
    l1=""
    if 0.25<=r["prob"][i]<0.5 and r["lead_present"][i]<0.5: l1="<-- prob低于门但>0.25"
    print(f"{r['tr'][i]:7.2f} {r['vEgo'][i]:5.2f} {r['prob'][i]:5.2f} {int(r['lead_present'][i]>0.5):5d} {r['mdes'][i]:6.2f} {r['a_plan'][i]:7.2f} {r['src'][i]:>7}  {l1}")
