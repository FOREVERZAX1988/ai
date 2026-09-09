#!/usr/bin/env python3
"""0070全段loes事件清单: OP发起步确认(loes=1)→起步结果分类(成功/掉st2/st6)"""
import glob
from openpilot.tools.lib.logreader import LogReader

def sig(d,pos,n,sc,off=0.0):
    raw=0
    for i in range(n):
        b=(pos+i)//8; bit=(pos+i)%8
        if b<len(d) and d[b]&(1<<bit): raw|=1<<i
    return raw*sc+off

wtx='se'+'nd'+'can'
fs=sorted(glob.glob('/data/media/0/realdata/00000070--*/rlog.zst'), key=lambda f:int(f.split('--')[-1].split('/')[0]))
for f in fs:
    seg=f.split('--')[-1].split('/')[0]
    t0=None; loes_prev=False; ev_start=None; ev=[]; buf=[]
    # 收集全段精简帧流(0.1s)
    for m in LogReader(f):
        t=m.logMonoTime/1e9
        if t0 is None: t0=t
        tt=t-t0
        w=m.which()
        try:
            if w=='carState':
                cs=m.carState
                buf.append((tt,'CS',f"v{cs.vEgo*3.6:4.0f} g{int(cs.gasPressed)} en{int(cs.cruiseState.enabled)}"))
            elif w==wtx:
                for c in getattr(m,wtx):
                    if c.address==269 and len(c.dat)>=8:
                        loes=sig(c.dat,43,1,1); st=sig(c.dat,57,3,1)
                        buf.append((tt,'OP',f"st{st:.0f} loes{loes:.0f}"))
            elif w=='can':
                for c in m.can:
                    if c.address==269 and c.src==2 and len(c.dat)>=8:
                        st=sig(c.dat,57,3,1); loes=sig(c.dat,43,1,1)
                        buf.append((tt,'ST',f"st{st:.0f} loes{loes:.0f}"))
        except Exception: pass
    # 找OP loes上升沿→窗口
    buf.sort(key=lambda x:x[0])
    loes_prev=False
    for tt,tag,s in buf:
        if tag=='OP' and 'loes1' in s:
            if not loes_prev: ev.append(tt)
            loes_prev=True
        elif tag=='OP' and 'loes0' in s:
            loes_prev=False
    if ev:
        # 去重(相近时刻合并)
        dedup=[]
        for e in ev:
            if dedup and e-dedup[-1]<3: continue
            dedup.append(e)
        ev=dedup
        # 对每个事件判结果
        for e in ev:
            win=[x for x in buf if e-1<=x[0]<=e+8]
            vmax=0; st6=False; st2=False; gas=False; st3_after=False; v10=0
            st_prev=None
            for tt,tag,s in win:
                if tag=='CS':
                    v=float(s.split('v')[1].split('g')[0])
                    vmax=max(vmax,v)
                    if 'g1' in s: gas=True
                    if v>10: v10=tt-e
                elif tag=='OP':
                    if 'st6' in s: st6=True
                    if 'st2' in s and st_prev=='st3': st2=True
                    if 'st3' in s and tt>e: st3_after=True
                    if 'st' in s: st_prev=s.split('loes')[0].replace('st','').strip()
            result='成功(st3+v10)' if (st3_after and v10) else ('st6故障' if st6 else ('掉st2' if st2 else '未起步'))
            print(f"seg{seg} loes@{e:6.1f}s vmax{vmax:4.0f}kmh gas{'Y' if gas else 'N'} → {result}")
