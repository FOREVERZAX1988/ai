import subprocess, time, re, statistics, json, datetime, glob, os

PEER = "192.168.10.65"; DUR = 60
OUT = "/data/tmp/stability_report_v3.json"
rows = []
t0 = time.time()
while time.time() - t0 < DUR:
    ts = time.time() - t0
    txt = subprocess.run(["ss", "-tinmH", "dst", PEER], capture_output=True, text=True).stdout
    r = {"t": round(ts, 2), "estab": 0, "sendq": None, "recvq": None, "rtt": None, "rttvar": None,
         "cwnd": None, "retr": 0, "unacked": None, "notsent": None, "skmem": None}
    for l in txt.splitlines():
        f = l.split()
        if f and f[0] == "ESTAB":
            r["estab"] = 1
            try: r["recvq"], r["sendq"] = int(f[1]), int(f[2])
            except Exception: pass
        m = re.search(r"rtt:([\d.]+)/([\d.]+)", l)
        if m: r["rtt"], r["rttvar"] = float(m.group(1)), float(m.group(2))
        m = re.search(r"cwnd:(\d+)", l)
        if m: r["cwnd"] = int(m.group(1))
        m = re.search(r"retrans:(\d+)/(\d+)", l)
        if m: r["retr"] = int(m.group(1))
        m = re.search(r"unacked:(\d+)", l)
        if m: r["unacked"] = int(m.group(1))
        m = re.search(r"notsent:(\d+)", l)
        if m: r["notsent"] = int(m.group(1))
        m = re.search(r"skmem:\((.*?)\)", l)
        if m: r["skmem"] = m.group(1)
    rows.append(r)
    time.sleep(1)

def st(v):
    v = [x for x in v if x is not None]
    if not v: return None
    return {"n": len(v), "min": min(v), "p50": round(statistics.median(v), 2), "p95": sorted(v)[max(0, int(len(v)*0.95)-1)],
            "max": max(v), "std": round(statistics.pstdev(v), 2) if len(v) > 1 else 0.0}

def diffs(v):
    v = [x for x in v if x is not None]
    return st([abs(b-a) for a, b in zip(v, v[1:])])

rep = {"generated": datetime.datetime.now().isoformat(), "peer": PEER, "window_s": DUR,
       "estab_samples": sum(r["estab"] for r in rows), "n": len(rows),
       "sendq_bytes": st([r["sendq"] for r in rows]),
       "sendq_jitter_bytes": diffs([r["sendq"] for r in rows]),
       "sendq_nonzero_ratio": round(sum(1 for r in rows if (r["sendq"] or 0) > 0)/len(rows), 3),
       "sendq_peak_samples": sorted([r for r in rows if r["sendq"]], key=lambda r: -r["sendq"])[:5],
       "rtt_ms": st([r["rtt"] for r in rows]), "rtt_jitter_ms": diffs([r["rtt"] for r in rows]),
       "rttvar_ms": st([r["rttvar"] for r in rows]),
       "cwnd": st([r["cwnd"] for r in rows]), "cwnd_jitter": diffs([r["cwnd"] for r in rows]),
       "retrans_max": max(r["retr"] for r in rows),
       "unacked": st([r["unacked"] for r in rows]),
       "notsent": st([r["notsent"] for r in rows]),
       "skmem_sample": next((r["skmem"] for r in rows if r["skmem"]), None)}
with open(OUT, "w") as f: json.dump({"summary": rep, "raw": rows}, f, indent=1)
print(json.dumps(rep, indent=1, ensure_ascii=False))
