import sys,glob,os
sys.path.insert(0,'/data/openpilot')
from openpilot.tools.lib.logreader import LogReader
rt=sys.argv[1]
for p in sorted(glob.glob('/data/media/0/realdata/'+rt+'--*/rlog.zst')):
    t0=None;t1=None;s6=[];vego=[]
    for e in LogReader(p):
        t=e.logMonoTime/1e9
        if t0 is None: t0=t
        t1=t
        if e.which()=='can':
            for m in e.can:
                if m.address==269 and m.src==2 and ((bytes(m.dat)[7]>>1)&7)==6: s6.append(round(t,2))
    print(os.path.basename(os.path.dirname(p)),'t=%.1f-%.1f'%(t0,t1),'err6',len(s6),s6[:6])
