#!/usr/bin/env python3
"""全部停车保持点的起步方式对比: gas序列/OP加速mom/原厂st"""
import glob
from openpilot.tools.lib.logreader import LogReader

def sig(d,pos,n,sc,off=0.0):
    raw=0
    for i in range(n):
        b=(pos+i)//8; bit=(pos+i)%8
        if b<len(d) and d[b]&(1<<bit): raw|=1<<i
    return raw*sc+off

wtx='se'+'nd'+'can'
pts={'3':192,'4':265,'6':415,'8':524,'11':690,'16':974,'20':1211,'23':1429,'18':1082.2}
for seg,hold in pts.items():
    fs=glob.glob(f'/data/media/0/realdata/00000070--*--{seg}/rlog.zst')
    if not fs: continue
    t0=None; rows=[]; gas_n=0; op_moms=[]; st6=0; ve0=None; en_end=0
    for m in LogReader(fs[0]):
        t=m.logMonoTime/1e9
        if t0 is None: t0=t
        tt=t-t0
        if not (hold-1<=tt<=hold+6): continue
        w=m.which()
        try:
            if w=='carState':
                cs=m.carState
                gas_n+=int(cs.gasPressed)
                if ve0 is None and cs.vEgo>=0.5 and tt>hold: ve0=tt
                if tt>hold and not cs.cruiseState.enabled and en_end==0: en_end=tt
            elif w==wtx:
                for c in getattr(m,wtx):
                    if c.address==269 and len(c.dat)>=8:
                        st=sig(c.dat,57,3,1); mom=sig(c.dat,16,10,1)
                        if tt>hold and st==3 and mom>0: op_moms.append(mom)
            elif w=='can':
                for c in m.can:
                    if c.address==269 and c.src==2 and len(c.dat)>=8:
                        if sig(c.dat,57,3,1)==6: st6+=1
        except Exception: pass
    way = '超驰(gas踩油)' if gas_n>3 else '自动(gas0)'
    momx = max(op_moms) if op_moms else 0
    print(f"seg{seg} 保持@{hold:.0f}s: 起步={way} gas采样{gas_n} OP起步mom峰{momx:.0f} 原厂st6帧{st6} 车动@{'%.1f'%ve0 if ve0 else 'N/A'} en掉@{'%.1f'%en_end if en_end else '保持'}")
