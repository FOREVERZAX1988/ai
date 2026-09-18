#!/usr/bin/env python3
"""Scan Macan ACC radar handshake: compare known-good fusion routes (0078/0079)
vs failing pure-OP route (0075). Tracks ACC_04 Charisma cluster + ACC_05 status.
DBC (vw_mlb.dbc):
  ACC_04(804) ACC_Charisma_FahrPr=bit56|3, Status=bit59|2(0=Init,1=avail,2=not_avail), Umsch=bit61|2
  ACC_05(269) ACC_Status_ACC = bit57|3 (0=off,2=standby,3=active,6/7=fault)
Run: cd /data/openpilot && python3 ai/tools/scan_macan_radar_handshake2.py
"""
import sys
sys.path.insert(0,'/data/openpilot'); sys.path.insert(0,'/data/openpilot/openpilot')
sys.path.insert(0,'/data/openpilot/openpilot/opendbc_repo')
from tools.lib.logreader import LogReader

ROUTES = {
  'WORKING 0078': '00000078--faf5174959--0/rlog.zst',
  'WORKING 0079': '00000079--5759194cf4--0/rlog.zst',
  'FAILING 0075': '00000075--77231a5ef1--0/rlog.zst',
}

def handshake_summary(path,label,window_ms=60000,maxframes=700000):
    lr=LogReader(path); t0=None; n=0
    seen_start=first_ready=fault_t=None; final_st=final_chr=None
    for m in lr:
        n+=1
        if n>maxframes: break
        if m.which()!='can': continue
        t=m.logMonoTime
        if t0 is None: t0=t
        ms=(t-t0)/1e6
        if ms>window_ms: break
        for c in m.can:
            if len(c.dat)<8 or c.src!=2: continue
            b=bytes(c.dat)
            if c.address==804:
                chr_=(b[7]>>3)&3
                if seen_start is None: seen_start=ms
                if chr_==1 and first_ready is None: first_ready=ms
                final_chr=chr_
            elif c.address==269:
                st=(b[7]>>1)&7
                if final_st is None and st!=0: final_st=st
                if st in (6,7) and fault_t is None: fault_t=ms
    print('%-16s ACC04@%.0fms  Chr->1(ready)@%.0fms  radar_fault(st6/7)@%s  ACC05st(late)=%s ChrStatus(late)=%s'%(
        label, seen_start or -1, first_ready or -1,
        '%.0f'%fault_t if fault_t else 'NEVER', final_st, final_chr))

if __name__=='__main__':
    print('Macan ACC radar handshake scan (bus2 = original radar):')
    print('='*100)
    for lab,r in ROUTES.items():
        handshake_summary('/data/media/0/realdata/'+r, lab)
