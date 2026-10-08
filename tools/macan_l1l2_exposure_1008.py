#!/usr/bin/env python3
"""L1/L2 修复的"路面正常驾驶"暴露面探针（2026-10-08 route 92）

度量（只在 engage 且有前车/无前车区分）：
 L2: mdes < -0.2 且 longitudinalPlanSource != e2e 的帧 —— 现行 is_e2e 不放行，L2 会新放行。
     - 其中「无 lead + vEgo>5 m/s + 模型只是轻度踩刹」= 高速空路新增刹车暴露
     - 连续段时长分布
 L1: 视觉 prob 落在 [0.25,0.5) 且 0.5s 内曾有 prob>=0.5（=L1 会 hold 的帧），按速度分层
"""
import os, sys, numpy as np
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
BASE="/data/media/0/realdata"; CACHE="/data/openpilot/ai/tools/cache_l1l2_1008"

def parse(seg):
    os.makedirs(CACHE, exist_ok=True); cf=f"{CACHE}/{seg}.npz"
    if os.path.exists(cf): return True
    qp, rp = f"{BASE}/{seg}/qlog.zst", f"{BASE}/{seg}/rlog.zst"
    if not (os.path.exists(qp) and os.path.exists(rp)): return False
    qt,qv=[],[]
    for m in LogReader(qp):
        if m.which()=="carState":
            qt.append(m.logMonoTime/1e9); qv.append(m.carState.vEgo)
    mt,mp,mx,mv,ma=[],[],[],[],[]
    rt,rp_,rd,rmp=[],[],[],[]
    lt,la,ls=[],[],[]
    st,se,sm=[],[],[]
    for m in LogReader(rp):
        w=m.which(); t=m.logMonoTime/1e9
        if w=="modelV2":
            lv=m.modelV2.leadsV3
            mt.append(t); ma.append(float(m.modelV2.action.desiredAcceleration))
            if len(lv)>0:
                mp.append(float(lv[0].prob)); mx.append(float(lv[0].x[0])); mv.append(float(lv[0].v[0]))
            else:
                mp.append(0.0); mx.append(np.nan); mv.append(np.nan)
        elif w=="radarState":
            lo=m.radarState.leadOne
            rt.append(t); rp_.append(1.0 if lo.present else 0.0); rd.append(float(lo.dRel)); rmp.append(float(lo.modelProb))
        elif w=="longitudinalPlan":
            lt.append(t); la.append(float(m.longitudinalPlan.accels[0]))
            try: ls.append(str(m.longitudinalPlan.longitudinalPlanSource))
            except Exception: ls.append("?")
        elif w=="selfdriveState":
            st.append(t); se.append(1.0 if m.selfdriveState.enabled else 0.0)
            sm.append(1.0 if m.selfdriveState.experimentalMode else 0.0)
    T=np.array(mt)
    if len(T)==0: return False
    def near(x,y,t):
        x=np.array(x); y=np.array(y)
        if len(x)==0: return np.full_like(t,np.nan)
        i=np.clip(np.searchsorted(x,t,side="right")-1,0,len(x)-1); return y[i]
    d=dict(t=T,mdes=np.array(ma),prob=np.array(mp),vis_x=np.array(mx),vis_v=np.array(mv),
           lead_present=near(rt,rp_,T),d_fus=near(rt,rd,T),lead_mprob=near(rt,rmp,T),
           a_plan=near(lt,la,T),src=np.array(near(lt,ls,T).tolist(),dtype=object),
           enabled=near(st,se,T),expmode=near(st,sm,T))
    d["vEgo"]=np.interp(T,np.array(qt),np.array(qv))
    np.savez_compressed(cf,**d)
    return True

def episodes(mask, t, min_dur=0.0):
    out=[]; i=0
    while i<len(mask):
        if mask[i]:
            j=i
            while j+1<len(mask) and mask[j+1]: j+=1
            if t[j]-t[i]>=min_dur: out.append((t[i],t[j]-t[i]))
            i=j+1
        else: i+=1
    return out

if __name__=="__main__":
    import time
    segs=[f"00000092--d83e53a0c7--{i}" for i in range(1,16)]
    only=sys.argv[1:] or segs
    for s in only:
        t0=time.time(); ok=parse(s)
        print(f"parse {s}: {ok} {time.time()-t0:.0f}s", flush=True)
