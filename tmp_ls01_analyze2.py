import sys
sys.path.insert(0, '/data/openpilot')
sys.path.insert(0, '/data/openpilot/msgq_repo')
from openpilot.tools.lib.logreader import LogReader

LOGS = [f'/data/media/0/realdata/00000079--5759194cf4--{i}/rlog.zst' for i in range(5)]
LS01 = 267

def has_set(dat): return (bytes(dat)[2] & 1) == 1
def has_resume(dat): return ((bytes(dat)[2] >> 3) & 1) == 1
def get_main(dat): return (bytes(dat)[1] >> 4) & 1

print("=== Bus1 physical SET press, with panda lon state, and whether a bus194 drop happened around the same time (within 200ms) ===")
for seg, path in enumerate(LOGS):
    lr = LogReader(path)
    ca = False
    events = []  # (t, desc)
    for msg in lr:
        w = msg.which()
        t = msg.logMonoTime/1e9
        if w == 'pandaStates':
            for ps in msg.pandaStates:
                ca = ps.controlsAllowed
        elif w == 'can':
            s1 = False
            drops = []
            for c in msg.can:
                if c.address != LS01: continue
                if c.src == 1 and has_set(c.dat): s1 = True
                if c.src == 194 and (has_set(c.dat) or has_resume(c.dat)):
                    drops.append('set' if has_set(c.dat) else 'resume')
            if s1:
                events.append((t, 'SET_bus1', ca))
            if drops:
                events.append((t, f'drop:{",".join(drops)}', ca))
    # merge print with grouping
    print(f"\n--- SEG {seg} ---")
    for t, desc, ca in events:
        print(f"  t={t:.3f} {desc} panda_lon={ca}")
print("\ndone")