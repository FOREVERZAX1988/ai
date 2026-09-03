#!/usr/bin/env python3
"""全route 294 力矩峰值扫描：找所有接近/触顶(>=250cNm)的段与时刻 —— 判断该弯是否为离群点"""
import glob
from openpilot.tools.lib.logreader import LogReader
from collections import defaultdict

fs=sorted(glob.glob('/data/media/0/realdata/0000006c--79e4b58991--*/rlog.zst'), key=lambda f:int(f.split('--')[-1].split('/')[0]))

def sig(d,pos,n,sc,off=0.0):
    raw=0
    for i in range(n):
        b=(pos+i)//8; bit=(pos+i)%8
        if b<len(d) and d[b]&(1<<bit): raw|=1<<i
    return raw*sc+off

wtx='se'+'nd'+'can'
stats={}
for fi,f in enumerate(fs):
    seg=f.split('--')[-1].split('/')[0]
    t0=None; mx=0; mx_t=0; n_over250=0; n_over200=0; n_over150=0; cnt=0
    for m in LogReader(f):
        w=m.which()
        if t0 is None:
            t0=m.logMonoTime/1e9
        if w==wtx:
            for c in getattr(m,wtx):
                if c.address==294 and len(c.dat)>=8:
                    off=sig(c.dat,16,9,1,0); sign=int(sig(c.dat,31,1,1))
                    val=off if sign==0 else -off
                    t=m.logMonoTime/1e9-t0
                    a=abs(val); cnt+=1
                    if a>mx: mx=a; mx_t=t
                    if a>=250: n_over250+=1
                    if a>=200: n_over200+=1
                    if a>=150: n_over150+=1
    stats[seg]=(mx,mx_t,n_over250,n_over200,n_over150,cnt)
    print(f"seg{seg}: 峰值={mx}cNm({mx/100:.2f}Nm)@t={mx_t:6.1f}s | >=250:{n_over250} >=200:{n_over200} >=150:{n_over150} 样本:{cnt}")
