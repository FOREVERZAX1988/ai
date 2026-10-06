import pickle, sys
rows = pickle.load(open('/data/openpilot/ai/tools/_sngele.pkl', 'rb'))
lo, hi = float(sys.argv[1]), float(sys.argv[2])
sel = [r for r in rows if lo <= r[1] <= hi]
sel.sort(key=lambda r: r[1])
prev = {}
for r in sel:
    k = r[0]
    if prev.get(k) == r[2:]:
        continue
    prev[k] = r[2:]
    t = r[1]
    p = r[2:]
    if k == 'f5':
        print(f"{t:8.2f} F5 st={p[0]} vz={p[1]:5.2f} mom={p[2]:3d} anh={p[3]} lo={p[4]}")
    elif k == 'o5':
        print(f"{t:8.2f} O5 st={p[0]} vz={p[1]:5.2f} mom={p[2]:3d} anh={p[3]} lo={p[4]}")
    elif k == 'f2':
        print(f"{t:8.2f} F2 idx={p[0]:4d} rel={p[1]&3} prio={p[2]} prim={p[3]} stanz={p[4]} txt={p[1]>>2} w={p[5]}")
    elif k == 'o2':
        print(f"{t:8.2f} O2 idx={p[0]:4d} rel={p[1]&3} prio={p[2]} prim={p[3]} stanz={p[4]} txt={p[1]>>2} w={p[5]}")
    elif k == 'cs':
        print(f"{t:8.2f} CS v={p[0]:5.2f} std={int(p[1])} gas={int(p[2])}")
    elif k == 'rd':
        print(f"{t:8.2f} RD lead={int(p[0])} d={p[1]:5.1f} vl={p[2]:5.1f}")
print('rows', len(sel))
