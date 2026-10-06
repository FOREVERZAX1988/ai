import pickle, bisect

rows = pickle.load(open('/data/openpilot/ai/tools/_sngele.pkl', 'rb'))
d = {}
for r in rows:
    d.setdefault(r[0], []).append((r[1], r[2:]))
for k in d:
    d[k].sort()
ts = {}
for k, v in d.items():
    ts[k] = [x[0] for x in v]

def snap(k, t):
    i = bisect.bisect_right(ts.get(k, []), t) - 1
    return d[k][i][1] if i >= 0 else None

allt = sorted(set([x[1] for x in rows]))
prev = {}
out = []
lastg = -9
for t in allt:
    s = {}
    for k in ('cs', 'rd', 'f5', 'o5', 'f2', 'o2'):
        s[k] = snap(k, t)
    key = (s['cs'][1] if s['cs'] else None,
           s['cs'][2] if s['cs'] else None,
           s['rd'][0] if s['rd'] else None,
           s['f5'][0] if s['f5'] else None, s['f5'][4] if s['f5'] else None,
           s['o5'][0] if s['o5'] else None, s['o5'][4] if s['o5'] else None,
           (s['f2'][0] > 0) if s['f2'] else None, (s['o2'][0] > 0) if s['o2'] else None)
    if key != prev or t - lastg > 2.0:
        prev = key
        lastg = t
        out.append((round(t, 2), s))
for t, s in out:
    cs = s['cs'] or (0, 0, 0)
    rd = s['rd'] or (0, 0, 0)
    f5 = s['f5'] or (0, 0, 0, 0, 0)
    o5 = s['o5'] or (0, 0, 0, 0, 0)
    f2 = s['f2'] or (0, 0, 0, 0, 0, 0)
    o2 = s['o2'] or (0, 0, 0, 0, 0, 0)
    print(f"t={t:7.2f} v={cs[0]:5.2f} std={int(cs[1])} gas={int(cs[2])} ldr={int(rd[0])}:{rd[1]:5.1f}m "
          f"|F5 st={f5[0]} vz={f5[1]:5.2f} mom={f5[2]:3d} anh={f5[3]} lo={f5[4]} "
          f"|O5 st={o5[0]} vz={o5[1]:5.2f} mom={o5[2]:3d} anh={o5[3]} lo={o5[4]} "
          f"|F2 idx={f2[0]:4d} rel={f2[1]} |O2 idx={o2[0]:4d} rel={o2[1]}")
print('events', len(out))
