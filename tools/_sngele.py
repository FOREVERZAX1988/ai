import sys, glob, pickle
sys.path.insert(0, '/data/openpilot')
from openpilot.tools.lib.logreader import LogReader

rt = sys.argv[1]
lo, hi = float(sys.argv[2]), float(sys.argv[3])

def g(x, s, n):
    return (int.from_bytes(x, 'little') >> s) & ((1 << n) - 1)

rows = []
for p in sorted(glob.glob('/data/media/0/realdata/' + rt + '--*/rlog.zst')):
    for e in LogReader(p):
        t = e.logMonoTime / 1e9
        if t < lo or t > hi:
            continue
        w = e.which()
        if w == 'can':
            for m in e.can:
                x = bytes(m.dat)
                if m.address == 269 and m.src == 2:
                    rows.append(('f5', t, g(x, 57, 3), round(g(x, 32, 11) * 0.005 - 7.22, 2), g(x, 16, 10), g(x, 62, 1), g(x, 43, 1)))
                elif m.address == 780 and m.src == 2:
                    rows.append(('f2', t, g(x, 24, 10), g(x, 46, 3), g(x, 44, 2), g(x, 22, 2), g(x, 61, 3), round(g(x, 12, 10) * 0.32, 1)))
                elif m.address == 269 and m.src in (0, 128):
                    rows.append(('o5', t, g(x, 57, 3), round(g(x, 32, 11) * 0.005 - 7.22, 2), g(x, 16, 10), g(x, 62, 1), g(x, 43, 1)))
                elif m.address == 780 and m.src in (0, 128):
                    rows.append(('o2', t, g(x, 24, 10), g(x, 46, 3), g(x, 44, 2), g(x, 22, 2), g(x, 61, 3), round(g(x, 12, 10) * 0.32, 1)))
        elif w == 'carState':
            rows.append(('cs', t, round(e.carState.vEgo, 2), e.carState.standstill, e.carState.gasPressed))
        elif w == 'radarState':
            l = e.radarState.leadOne
            rows.append(('rd', t, l.present, round(l.dRel, 1), round(l.vLead, 1)))
rows.sort(key=lambda r: r[1])
pickle.dump(rows, open('/data/openpilot/ai/tools/_sngele.pkl', 'wb'))
print('rows', len(rows), 't', rows[0][1], rows[-1][1])
