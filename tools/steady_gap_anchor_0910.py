#!/usr/bin/env python3
"""稳态跟车锚：gate(两车速度一致) & 前车速度≈自车速度 => 真稳态段，t_vis=d/v 即真实时距。
检验原厂 ZL 语义（t_vis 是否落在整数秒）+ 两分支一致性。"""
import sys, numpy as np
SC="/data/openpilot/ai/tools/.scan2"
BR={'00000002':'OLD','00000003':'OLD','00000004':'OLD','00000049':'OLD','00000071':'NEW','00000072':'NEW'}
for rt in ['00000002','00000004','00000049','00000071','00000072','00000003']:
    d=np.load(f"{SC}/{rt}.npz")
    idx,zl,v,dv,vlr,vv,gate=[d[k] for k in ('idx','zl','v','dv','vlr','vv','gate')]
    t=dv/np.maximum(v,5.0)
    steady=gate&np.isfinite(vv)&np.isfinite(vlr)&(np.abs(vv-v)<0.4)&(np.abs(vlr-v)<0.4)&(idx>100)&(idx<1020)
    print(f"\n=== {rt} [{BR[rt]}]  总帧={len(idx)} 稳态段={steady.sum()} ({100*steady.sum()/max(len(idx),1):.1f}%) ===")
    print(f"  {'zl':>3} {'n':>7} {'idx中位':>7} {'v(km/h)':>8} {'t_vis中位':>9} {'t_old':>7} {'t_new':>7} {'t_vis/t_old':>11}")
    for z in sorted(set(zl[steady].astype(int))):
        m=steady&(zl==z)
        if m.sum()<200: continue
        imm=np.median(idx[m]); vm=np.median(v[m]); tm=np.median(t[m])
        import json
        IDX=np.array(json.load(open('/data/openpilot/ai/tools/abstands_idx_table.json')))
        TT=np.array(json.load(open('/data/openpilot/ai/tools/abstands_t_table.json')))
        to=np.interp(imm,IDX,TT); tn=0.008718*imm+1.0178
        print(f"  {z:>3} {m.sum():>7} {imm:>7.0f} {vm*3.6:>8.1f} {tm:>9.3f} {to:>7.3f} {tn:>7.3f} {tm/to:>11.3f}")
