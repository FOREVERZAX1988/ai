#!/usr/bin/env python3
"""
scan_override_neg.py — 原厂超驰(st=4)期间 verz<0 窗口的精确时间段提取
用法: python3 scan_override_neg.py ROUTE_PREFIX [..]
输出: 每段中 st=4 且 verz<0 的连续窗口 → [段 | 相对段起点秒 s.s | verz min~max | 帧数 | FV/FM]
依赖: vw_mlb.dbc BO_269 帧内提取（防同名错配）
"""
import sys, os, re, glob
sys.path.insert(0, "/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
DBC = "/data/openpilot/opendbc_repo/opendbc/dbc/vw_mlb.dbc"
BASE = "/data/media/0/realdata"
def get_sigs():
    lines=open(DBC,encoding="latin-1").read().splitlines()
    s=next(i for i,l in enumerate(lines) if l.startswith('BO_ 269 '))
    e=next(i for i in range(s+1,len(lines)) if lines[i].startswith('BO_ '))
    out={}
    for l in "\n".join(lines[s:e]).splitlines():
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
NAME={'ACC_Status_ACC','ACC_Verz_anf','ACC_Freigabe_Verzanf','ACC_Freigabe_Momentenanf'}
def main():
    S=get_sigs()
    for pref in sys.argv[1:]:
        segs=sorted(glob.glob(f"{BASE}/{pref}--*"))
        win_total=0
        for seg in segs:
            path=os.path.join(seg,"rlog.zst")
            if not os.path.exists(path): continue
            rn=os.path.basename(seg)
            try: lr=LogReader(path)
            except Exception as ex: print(f"[{rn}] fail:{ex}"); continue
            t0=None; win=[]; wins=[]
            for msg in lr:
                if msg.which()!='can': continue
                ts=msg.logMonoTime/1e9
                if t0 is None: t0=ts
                cur=ts-t0
                for c in msg.can:
                    if c.address==269 and c.src==2 and len(c.dat)>=8:
                        d=bytes(c.dat)
                        st=int(gs(d,*S['ACC_Status_ACC'])); verz=gs(d,*S['ACC_Verz_anf'])
                        fv=int(gs(d,*S['ACC_Freigabe_Verzanf'])); fm=int(gs(d,*S['ACC_Freigabe_Momentenanf']))
                        if st==4 and verz<0:
                            win.append((cur,verz,fv,fm))
                        elif win:
                            wins.append((win[0][0],win[-1][0],min(w[1] for w in win),max(w[1] for w in win),
                                        len(win),win[-1][2],win[-1][3]))
                            win=[]
            if win:
                wins.append((win[0][0],win[-1][0],min(w[1] for w in win),max(w[1] for w in win),
                             len(win),win[-1][2],win[-1][3]))
            for (a,b,vmin,vmax,n,nfv,nfm) in wins:
                win_total+=1
                print(f"[{rn}] t={a:.1f}~{b:.1f}s (dur={b-a:.1f}s) verz={vmin:.2f}~{vmax:.2f} 帧数={n} 尾FV={nfv}/FM={nfm}")
        print(f"[{pref}] 负verz超驰窗口合计 {win_total} 个")
if __name__=='__main__': main()
