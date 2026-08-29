#!/usr/bin/env python3
"""scan_neg_global.py — 负verz超驰窗口 + route全局时间
逐个段累加前段实际时长，板材全局秒 = 累计偏移 + 段内秒。
只读 rlog，不控车。
"""
import glob,os,sys
sys.path.insert(0,"/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
DBC="/data/openpilot/opendbc_repo/opendbc/dbc/vw_mlb.dbc"
BASE="/data/media/0/realdata"
NAME={'ACC_Status_ACC','ACC_Verz_anf','ACC_Freigabe_Verzanf','ACC_Freigabe_Momentenanf'}
def sigs():
    L=open(DBC,encoding="latin-1").read().splitlines()
    s=next(i for i,l in enumerate(L) if l.startswith('BO_ 269 '))
    e=next(i for i in range(s+1,len(L)) if L[i].startswith('BO_ '))
    out={}
    for l in "\n".join(L[s:e]).splitlines():
        m=__import__('re').match(r'^\s*SG_ (\w+) : (\d+)\|(\d+)@(\d)([+-]) \(([0-9.eE+-]+),([0-9.eE+-]+)\)',l)
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
for pref in sys.argv[1:]:
    globs=sorted(glob.glob(BASE+"/"+pref+"--*"), key=lambda p:int(p.split('--')[-1]))
    global_off=0.0
    S=sigs(); tot=0
    for seg in globs:
        n=int(seg.split('--')[-1]); r=os.path.join(seg,"rlog.zst")
        if not os.path.exists(r): continue
        rn=os.path.basename(seg)
        try: lr=LogReader(r)
        except Exception as ex: print(f"[{rn}] fail:{ex}"); continue
        start=None; end=None; win=[]; seglist=[]
        for m in lr:
            if m.which()!='can': continue
            ts=m.logMonoTime/1e9
            if start is None: start=ts
            end=ts
            cur=ts-start
            for c in m.can:
                if c.address==269 and c.src==2 and len(c.dat)>=8:
                    d=bytes(c.dat)
                    st=int(gs(d,*S['ACC_Status_ACC'])); vz=gs(d,*S['ACC_Verz_anf'])
                    fv=int(gs(d,*S['ACC_Freigabe_Verzanf'])); fm=int(gs(d,*S['ACC_Freigabe_Momentenanf']))
                    if st==4 and vz<0:
                        win.append((cur,vz,fv,fm))
                    elif win:
                        a,b,vmin,vmx,lnw=win[0][0],win[-1][0],min(w[1] for w in win),max(w[1] for w in win),len(win)
                        seglist.append((a,global_off+a,b,global_off+b,vmin,vmx,lnw,win[-1][2],win[-1][3])); win=[]
        if win:
            a,b,vmin,vmx,lnw=win[0][0],win[-1][0],min(w[1] for w in win),max(w[1] for w in win),len(win)
            seglist.append((a,global_off+a,b,global_off+b,vmin,vmx,lnw,win[-1][2],win[-1][3]))
        for (aL,gA,bL,gB,vmin,vmx,lnw,nfv,nfm) in seglist:
            tot+=1
            mm,ss=divmod(gA,60); mm2,ss2=divmod(gB,60)
            ga=f"{int(mm)}分{ss:04.1f}秒"; gb=f"{int(mm2)}分{ss2:04.1f}秒"
            print(f"[{rn}] 全局 {ga}~{gb}  (段内{a:.1f}s) verz={vmin:.2f}~{vmx:.2f} {lnw}帧 尾FV={nfv}/FM={nfm}")
        if end: global_off += (end-start)
    print(f"[{pref}] 负verz超驰窗口 {tot} 个 (route累计时长 {int(global_off)}s = {int(global_off//60)}分{round(global_off%60)}秒)")
