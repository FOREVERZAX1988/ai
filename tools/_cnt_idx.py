import sys,glob,os
sys.path.insert(0,'/data/openpilot')
from openpilot.tools.lib.logreader import LogReader
rt=sys.argv[1]
for p in sorted(glob.glob('/data/media/0/realdata/'+rt+'--*/rlog.zst')):
    a=b=c=d=n=0; s6=0
    for e in LogReader(p):
        if e.which()=='can':
            for m in e.can:
                if m.address==780:
                    x=bytes(m.dat); i=(x[3]|(x[4]<<8))&1023; r=(x[5]>>6)&3
                    if m.src==2: a+=i>0; b+=r==1
                    elif m.src in (0,128): c+=i>0; d+=r==1
                elif m.address==269 and m.src==2 and ((bytes(m.dat)[7]>>1)&7)==6: s6+=1
    print(os.path.basename(os.path.dirname(p)), 'idx_factory',a,'idx_op',c,'rel_factory',b,'rel_op',d,'err6',s6)
