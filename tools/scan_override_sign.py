#!/usr/bin/env python3
"""scan_override_sign.py — 超驰(st=4)时段 verz/axG 符号分布（按有无前车分组）
验证假设: 有前车目标时超驰, 原厂 verz/axG 是否不输出正值
用法: python3 scan_override_sign.py ROUTE [ROUTE...]
输出: st=4 帧按 dRel 有无分组, 统计 verz/axG 的正/负/零占比 + 有前车且verz>0的样本
"""
import sys, glob, os, re
sys.path.insert(0,"/data/openpilot")
from openpilot.tools.lib.logreader import LogReader
from multiprocessing import Pool
BASE="/data/media/0/realdata"
DBC="/data/openpilot/opendbc_repo/opendbc/dbc/vw_mlb.dbc"
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
S=sigs()
def scan_seg(arg):
    route,sp=arg
    seg=os.path.basename(os.path.dirname(sp)).split('--')[-1]
    has_target=False; cnt={'st4':0,'car':0,'vg':0,'vz':0,'vv':0,'ag':0,'az':0,'av':0,
                   'vg_nc':0,'vz_nc':0,'vv_nc':0,'ag_nc':0,'az_nc':0,'av_nc':0}
    samp=[]
    try:
        for m in LogReader(sp):
            w=m.which()
            if w=='can':
                for c in m.can:
                    if c.src==2 and len(c.dat)>=8:
                        if c.address==804:
                            # ACC_Geschw_Zielfahrzeug 40|10 @0.32, 无目标=327.36
                            gv=0
                            for i in range(10):
                                pos=40-i; b=pos//8; bit=pos%8
                                gv=(gv<<1)|((bytes(c.dat)[b]>>(7-bit))&1)
                            has_target = (gv*0.32) < 320.0
                        elif c.address==269:
                            d=bytes(c.dat)
                            st=int(gs(d,*S['ACC_Status_ACC']))
                            if st==4:
                                vz=gs(d,*S['ACC_Verz_anf']); axg=gs(d,*S['ACC_ax_Getriebe'])
                                mom=gs(d,*S['ACC_Momentenanforderung'])
                                cnt['st4']+=1
                                has_car = has_target
                                if has_car:
                                    cnt['car']+=1
                                    cnt['vg']+= vz>0.05; cnt['vz']+= vz<-0.05; cnt['vv']+= abs(vz)<=0.05
                                    cnt['ag']+= axg>0.05; cnt['az']+= axg<-0.05; cnt['av']+= abs(axg)<=0.05
                                    if vz>0.05 and len(samp)<5:
                                        samp.append(f"seg{seg}: 目标{vz*0.32 if False else '?':s} verz={vz:+.2f} axG={axg:+.2f} mom={mom:.0f}")
                                else:
                                    cnt['vg_nc']+= vz>0.05; cnt['vz_nc']+= vz<-0.05; cnt['vv_nc']+= abs(vz)<=0.05
                                    cnt['ag_nc']+= axg>0.05; cnt['az_nc']+= axg<-0.05; cnt['av_nc']+= abs(axg)<=0.05
    except Exception:
        pass
    return seg, cnt, samp
def main():
    routes=sys.argv[1:]
    if not routes: print("用法: scan_override_sign.py ROUTE [ROUTE...]"); return
    for route in routes:
        segs=sorted(glob.glob(f"{BASE}/{route}--*--*/rlog.zst"))
        with Pool(4) as pool:
            res=pool.map(scan_seg,[(route,sp) for sp in segs])
        tot={'st4':0,'car':0,'vg':0,'vz':0,'vv':0,'ag':0,'az':0,'av':0,
             'vg_nc':0,'vz_nc':0,'vv_nc':0,'ag_nc':0,'az_nc':0,'av_nc':0}
        samples=[]
        for seg,cnt,samp in res:
            for k in tot: tot[k]+=cnt[k]
            samples+=samp
        n=tot['st4']; car=tot['car']; nc=n-car
        print(f"\n===== {route}: 超驰帧 {n}, 有前车 {car}({car*100//max(n,1)}%), 无前车 {nc} =====")
        if car:
            print(f"[有前车 {car}帧] verz: 正{tot['vg']}({tot['vg']*100//car}%) 负{tot['vz']}({tot['vz']*100//car}%) 零{tot['vv']}({tot['vv']*100//car}%)")
            print(f"            axG: 正{tot['ag']}({tot['ag']*100//car}%) 负{tot['az']}({tot['az']*100//car}%) 零{tot['av']}({tot['av']*100//car}%)")
        if nc:
            print(f"[无前车 {nc}帧] verz: 正{tot['vg_nc']}({tot['vg_nc']*100//max(nc,1)}%) 负{tot['vz_nc']}({tot['vz_nc']*100//max(nc,1)}%) 零{tot['vv_nc']}({tot['vv_nc']*100//max(nc,1)}%)")
            print(f"            axG: 正{tot['ag_nc']}({tot['ag_nc']*100//max(nc,1)}%) 负{tot['az_nc']}({tot['az_nc']*100//max(nc,1)}%) 零{tot['av_nc']}({tot['av_nc']*100//max(nc,1)}%)")
        if samples:
            print(f"[有前车且verz>0 的样本({len(samples)})]:")
            for s in samples: print("  ",s)
        else:
            print("[有前车且verz>0 的样本: 0 个]")
if __name__=="__main__": main()
