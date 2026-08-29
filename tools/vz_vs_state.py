#!/usr/bin/env python3
"""vz_vs_state.py — verz 与车辆/目标状态相关性分析
对齐 verz(ACC_05) 与 aEgo/vEgo(车)、radarTracks 目标距离/相对速度
用法: python3 vz_vs_state.py ROUTE_PREFIX SEGNO
"""
import glob,os,sys,re
sys.path.insert(0,"/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
DBC="/data/openpilot/opendbc_repo/opendbc/dbc/vw_mlb.dbc"
BASE="/data/media/0/realdata"
def sigs():
    L=open(DBC,encoding="latin-1").read().splitlines()
    s=next(i for i,l in enumerate(L) if l.startswith('BO_ 269 '))
    e=next(i for i in range(s+1,len(L)) if L[i].startswith('BO_ '))
    out={}
    for l in "\n".join(L[s:e]).splitlines():
        m=re.match(r'^\s*SG_ (\w+) : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)',l)
        if m: out[m.group(1)]=(int(m.group(2)),int(m.group(3)),m.group(5)=='-',float(m.group(6)),float(m.group(7)))
    return out
def gs(d,sl,ln,sg,sc=1.0,of=0.0):
    if len(d)<=(sl+ln-1)//8: return 0
    v=0
    for i in range(ln):
        b=(sl+i)//8; bt=(sl+i)%8
        if d[b]&(1<<bt): v|=(1<<i)
    if sg and v&(1<<(ln-1)): v-=(1<<ln)
    return v*sc+of
pref,segno=sys.argv[1],int(sys.argv[2])
p=glob.glob(f"{BASE}/{pref}--*--{segno}/rlog.zst")
if not p: print("无段"); sys.exit(1)
S=sigs()
rows=[]
cs={}; rt=None
for m in LogReader(p[0]):
    w=m.which()
    if w=='carState':
        c=m.carState; cs={'vEgo':c.vEgo,'aEgo':c.aEgo}
    elif w=='radarTracks':
        pts=m.radarTracks.points
        if len(pts)>0:
            t0=pts[0]
            rt=(t0.dRel,t0.vRel,t0.deprecated.aRel if hasattr(t0.deprecated,'aRel') else None)
    elif w=='can':
        for c in m.can:
            if c.address==269 and c.src==2 and len(c.dat)>=8:
                d=bytes(c.dat)
                vz=gs(d,*S['ACC_Verz_anf']); st=int(gs(d,*S['ACC_Status_ACC']))
                rows.append((m.logMonoTime/1e9,cs,vz,st,rt))
# 输出 verz<0 附近的行
print(f"{'t(s)':>8} {'vEgo':>6} {'aEgo':>7} {'verz':>7} {'st':>3} {'dRel':>7} {'vRel':>7} {'aRel':>7}")
prev_vz=0.0
for t,c,vz,st,rt in rows:
    if vz<0 or prev_vz<0:
        dR = f"{rt[0]:.1f}" if rt else "-"
        vR = f"{rt[1]:+.2f}" if rt else "-"
        aR = f"{rt[2]:+.2f}" if (rt and rt[2]==rt[2]) else "-"
        print(f"{t%120:8.2f} {c.get('vEgo',0):6.2f} {c.get('aEgo',0):7.3f} {vz:7.3f} {st:3.0f} {dR:>7} {vR:>7} {aR:>7}")
    prev_vz=vz
