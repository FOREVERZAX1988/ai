from tools.lib.logreader import LogReader

def charisma_events(path, window_ms=12000):
    lr=LogReader(path); t0=None
    last=collections.defaultdict(lambda:None); out=[]; n=0
    for m in lr:
        if m.which()!='can': continue
        t=m.logMonoTime
        if t0 is None: t0=t
        ms=(t-t0)/1e6
        for c in m.can:
            if c.address==804 and len(c.dat)>=8:
                b=bytes(c.dat); fp=(b[7]>>0)&7; st=(b[7]>>3)&3; um=(b[7]>>5)&3
                key=(c.src,fp,st,um)
                if key!=last[(c.src,)]:
                    last[(c.src,)]=key
                    out.append((round(ms,1),c.src,'fp=%d st=%d um=%d'%(fp,st,um),b.hex()))
        n+=1
        if ms>window_ms or n>2000000: break
    return out
import collections
for route,label in [('00000079--5759194cf4','WORKING0079(fusion)'),('00000075--77231a5ef1','FAILING0075(pure-OP)')]:
    path='/data/media/0/realdata/%s--0/rlog.zst'%route
    ev=charisma_events(path,12000)
    print('====',label,'Acc_04 charisma state transitions (12s) ====')
    for ms,src,desc,hx in ev[:60]:
        print('  t=%8.1fms bus%-3s charisma(%s) raw=%s'%(ms,src,desc,hx))
    print()
