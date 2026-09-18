import sys
sys.path.insert(0, '/data/openpilot')
sys.path.insert(0, '/data/openpilot/msgq_repo')
from openpilot.tools.lib.logreader import LogReader

LOGS = [f'/data/media/0/realdata/00000079--5759194cf4--{i}/rlog.zst' for i in range(5)]
LS01 = 267

def has_set(dat): return (bytes(dat)[2] & 1) == 1
def has_resume(dat): return ((bytes(dat)[2] >> 3) & 1) == 1
def get_main(dat): return (bytes(dat)[1] >> 4) & 1

# Track bus semantics: 128=tx on bus0, 129=tx bus1, 130=tx bus2, 192/193/194=dropped on bus0/1/2
for seg, path in enumerate(LOGS):
    print(f"\n========== SEG {seg} ==========")
    lr = LogReader(path)
    for msg in lr:
        w = msg.which()
        t = msg.logMonoTime/1e9
        if w == 'can':
            for c in msg.can:
                if c.address == LS01 and c.src in (128,129,130,192,193,194):
                    st = has_set(c.dat); rs = has_resume(c.dat); mn=get_main(c.dat)
                    if st or rs:
                        print(f"  t={t:.3f} bus={c.src} set={st} resume={rs} main={mn} hex={bytes(c.dat).hex()}")
        elif w == 'pandaStates':
            pass
print("\ndone")