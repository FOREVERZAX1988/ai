#!/usr/bin/env python3
"""Capture a short jetlink-over-Wi-Fi stability window and summarise it.

Measures three things the driver asked for, from two independent sources:

* **kernel side** (`ss -tni`, 1 Hz): Send-Q backlog on the :5090 sockets, rtt and
  rttvar (TCP's own jitter estimate), retransmit counter, bytes_acked rate.
* **application side** (swaglog, written by modeld): the per-frame `jetlink:
  frame N ...` lines (frame-id cadence, warp/send ms, server gpu/queue/total ms),
  the periodic `jetlink: stages frames ...` aggregate (p50/p95/max per stage) and
  the periodic `jetlink: trips frames N over ... held H pipelined P span_s S ...`
  aggregate. In that aggregate `held` counts frames whose *reply was late*, so
  the previous model output had to be held over (it is a latency event, not a
  dropped frame); `pipelined` counts frames that never waited at all.

Frame interval variance is computed from consecutive sampled frame ids:
`interval_ms = 1000 / ((id2 - id1) / (t2 - t1))`. The sample rate of those lines
is ~1.5 Hz, so this is a smoothed cadence (it cannot resolve a single dropped
frame); the `trips` aggregate's `held` count is what covers that.

Usage:
  python3 ai/scripts/jetlink_stability_capture.py --duration 60
  python3 ai/scripts/jetlink_stability_capture.py --duration 5 --no-write   # smoke

Writes JSON to artifacts/jetlink_stability_<ts>.json and, unless --no-write, a
markdown summary to ai/docs/jetlink_stability_<YYYYMMDD>.md.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import statistics
import subprocess
import sys
import time

# swaglog stamps each record with an epoch `created`, so the capture window has to
# be measured on the realtime clock: a monotonic window cannot be compared to it.
_wall = time.clock_gettime
CLOCK_REALTIME = time.CLOCK_REALTIME

LOG_GLOB = "/data/log/swaglog.*"
# written by jetlink/comma/wifi.py on every discovery/dial: "<host>:<port>:<monotonic>"
PEER_FILE = "/data/.jetlink_wifi_peer"
FRAME_RE = re.compile(
  r"jetlink: frame (?P<frame>\d+) warp (?P<warp>[\d.]+) data (?P<data>[\d.]+) send (?P<send>[\d.]+) "
  + r"wait (?P<wait>[\d.]+) ms.*?server gpu (?P<gpu>[\d.]+) queue (?P<queue>[\d.]+) total (?P<total>[\d.]+) ms"
  + r".*?(\d+ lost, net drops (?P<drops>\d+))?")
STAGES_RE = re.compile(r"jetlink: stages frames (?P<frames>\d+) capture .*?warp (?P<warp>[\d./]+) "
                       + r"send (?P<send>[\d./]+) reply_wait (?P<rw>[\d./]+) publish (?P<pub>[\d./]+)")
STAGE_TICK_RE = re.compile(r"jetlink: stages frame (?P<frame>\d+) capture ")
TRIPS_RE = re.compile(r"jetlink: trips frames (?P<frames>\d+) over (?P<over>\d+) held (?P<held>\d+) "
                      + r"pipelined (?P<pipe>\d+) span_s (?P<span>[\d.]+) p50_ms (?P<p50>[\d.]+) "
                      + r"p99_ms (?P<p99>[\d.]+) max_ms (?P<max>[\d.]+) server_ms (?P<server>[\d.]+)")
RTT_RE = re.compile(r"rtt:(?P<rtt>[\d.]+)/(?P<rttvar>[\d.]+)")
FIELD_RE = re.compile(r"(\w+):([\d.]+)")
RETRANS_RE = re.compile(r"retrans:(\d+)/(\d+)")


def _pct(values, q):
  if not values:
    return None
  s = sorted(values)
  if len(s) == 1:
    return s[0]
  k = (len(s) - 1) * q
  lo, hi = int(k), min(int(k) + 1, len(s) - 1)
  return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _stats(values):
  if not values:
    return None
  return {"n": len(values), "mean": round(statistics.fmean(values), 3),
          "p50": round(_pct(values, .5), 3), "p95": round(_pct(values, .95), 3),
          "max": round(max(values), 3), "min": round(min(values), 3),
          "stdev": round(statistics.pstdev(values), 3)}


def peer_from_file():
  """The app Wi-Fi discovery last picked, as "<host>:<port>:<monotonic>"."""
  try:
    host, port, _ts = open(PEER_FILE).read().strip().split(":")
    return host, int(port)
  except Exception:
    return None, None


def sample_sockets(host=None, port=None):
  """One `ss -tni` read of the jetlink sockets: queue + tcp info per socket."""
  if port is None:
    host, port = peer_from_file()
  # The frames ride the TCP connection this device opened to the app's port, so
  # select on the destination port and then keep only that host: a socket to a
  # second device would otherwise be averaged into the same jitter series.
  sock_filter = f"( dport = :{port} )" if port else "( sport = :5090 )"
  try:
    out = subprocess.run(["ss", "-tni", "state", "established", sock_filter],
                         capture_output=True, text=True, timeout=5).stdout
  except Exception as e:
    return {"error": str(e), "sockets": []}
  socks, cur = [], None
  for line in out.splitlines()[1:]:
    if not line.strip():
      continue
    if line[0].isspace():                       # tcp-info continuation line
      if cur is None:
        continue
      m = RTT_RE.search(line)
      if m:
        cur["rtt_ms"] = float(m.group("rtt"))
        cur["rttvar_ms"] = float(m.group("rttvar"))
      m = RETRANS_RE.search(line)
      if m:
        cur["retrans"] = int(m.group(1))
        cur["retrans_total"] = int(m.group(2))
      f = dict(FIELD_RE.findall(line))
      for k in ("bytes_acked", "cwnd", "minrtt", "lastsnd", "lastack"):
        if k in f:
          cur[k] = float(f[k])
      continue
    parts = line.split()
    if len(parts) >= 4:
      cur = {"recv_q": int(parts[0]), "send_q": int(parts[1]),
             "local": parts[2], "peer": parts[3]}
      socks.append(cur)
  if host:
    socks = [x for x in socks if x["peer"].rsplit(":", 1)[0] == host]
  return {"sockets": socks, "peer": f"{host}:{port}" if port else None}


def scan_logs(t0, t1):
  """Every jetlink swaglog line written in [t0, t1], parsed by kind."""
  frames, stages, ticks, trips, others = [], [], [], [], []
  for path in sorted(glob.glob(LOG_GLOB), key=os.path.getmtime):
    if os.path.getmtime(path) < t0 - 5:
      continue
    try:
      fh = open(path, errors="ignore")
    except OSError:
      continue
    with fh:
      for line in fh:
        if '"msg$s": "jetlink' not in line:
          continue
        try:
          rec = json.loads(line)
        except Exception:
          continue
        t = rec.get("created", 0)
        if not (t0 <= t <= t1):
          continue
        msg = rec.get("msg$s", "")
        m = FRAME_RE.search(msg)
        if m:
          d = m.groupdict()
          frames.append({"t": t, "frame": int(d["frame"]), "warp": float(d["warp"]),
                         "send": float(d["send"]), "server_queue": float(d["queue"]),
                         "server_gpu": float(d["gpu"]), "server_total": float(d["total"]),
                         "drops": int(d["drops"]) if d["drops"] else None})
          continue
        m = STAGE_TICK_RE.search(msg)
        if m:
          ticks.append({"t": t, "frame": int(m.group("frame"))})
          continue
        m = STAGES_RE.search(msg)
        if m:
          stages.append({"t": t, "frames": int(m.group("frames")),
                         "warp": m.group("warp"), "send": m.group("send"),
                         "reply_wait": m.group("rw"), "publish": m.group("pub")})
          continue
        m = TRIPS_RE.search(msg)
        if m:
          trips.append({"t": t, **{k: float(v) for k, v in m.groupdict().items()}})
          continue
        others.append({"t": t, "msg": msg[:160]})
  return frames, stages, ticks, trips, others


PROC_OF_INTEREST = ("modeld", "jetlink_adapter", "webuid", "sunnypilot.ui", "carrot_man", "xiaoge_data")


def _proc_snapshot():
  """Busy jiffies per interesting process + whole system, for one sample."""
  snap = {}
  try:
    f = open("/proc/stat").readline().split()[1:]
    vals = [float(v) for v in f]
    snap["_sys"] = (sum(vals), vals[3] + (vals[4] if len(vals) > 4 else 0))
  except Exception:
    pass
  for pid in os.listdir("/proc"):
    if not pid.isdigit():
      continue
    try:
      cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\x00", b" ").decode(errors="ignore")
    except OSError:
      continue
    for name in PROC_OF_INTEREST:
      if name in cmd:
        try:
          st = open(f"/proc/{pid}/stat").read()
          fields = st[st.rindex(")") + 2:].split()
          snap.setdefault(name, []).append((pid, float(fields[11]) + float(fields[12])))
        except Exception:
          pass
        break
  return snap


def _max_temp():
  """Hottest real sensor. The `-usr` zones are the silicon's own sensors; the
  `lmh-dcvs-*` zones live in the same class but publish the LMH throttle floor
  (a constant 75.0 on this device), so a plain max over every zone would report
  75 °C on an idle unit and make the thermal check meaningless."""
  usr, any_zone = [], []
  for zone in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
    try:
      name = open(f"{zone}/type").read().strip()
      v = int(open(f"{zone}/temp").read().strip()) / 1000.0
    except Exception:
      continue
    if not 0 < v < 150:
      continue
    any_zone.append(v)
    if name.endswith("-usr"):
      usr.append(v)
  pool = usr or any_zone
  return max(pool) if pool else None


def cpu_series(samples):
  """Turn the raw snapshots into busy-percent series."""
  sys_pct, per = [], {}
  prev = None
  for s in samples:
    cur = s.get("cpu")
    if not cur:
      continue
    if prev:
      dtot = cur.get("_sys", (0, 0))[0] - prev.get("_sys", (0, 0))[0]
      didle = cur.get("_sys", (0, 0))[1] - prev.get("_sys", (0, 0))[1]
      if dtot > 0:
        sys_pct.append(100.0 * (dtot - didle) / dtot)
      for name, rows in cur.items():
        if name == "_sys":
          continue
        old = dict(prev.get(name, []))
        for pid, jif in rows:
          if pid in old and dtot > 0:
            per.setdefault(name, []).append(100.0 * (jif - old[pid]) / dtot)
    prev = cur
  return sys_pct, per


EVENT_PATTERNS = {
  "link_abandoned": r"link abandoned|no answer to \d+ frames",
  "demote": r"demot|handed back|leaving the link",
  "hold_gave_up": r"gave up|hold deadline",
  "reconnect": r"dialed|reconnect|joined mid-drive|backoff",
  "net_drops": r"net drops [1-9]",
  "lost_frames": r"[1-9]\d* lost",
}


def scan_events(t0, t1):
  counts = dict.fromkeys(EVENT_PATTERNS, 0)
  hits = []
  for path in sorted(glob.glob(LOG_GLOB), key=os.path.getmtime):
    if os.path.getmtime(path) < t0 - 5:
      continue
    try:
      fh = open(path, errors="ignore")
    except OSError:
      continue
    with fh:
      for line in fh:
        if '"msg$s": "jetlink' not in line and "LinkError" not in line:
          continue
        try:
          rec = json.loads(line)
        except Exception:
          continue
        t = rec.get("created", 0)
        if not (t0 <= t <= t1):
          continue
        msg = rec.get("msg$s", "")
        for name, pat in EVENT_PATTERNS.items():
          if re.search(pat, msg, re.I):
            counts[name] += 1
            if len(hits) < 20:
              hits.append({"at": time.strftime("%H:%M:%S", time.localtime(t)), "kind": name, "msg": msg[:140]})
  return counts, hits


def _fmt(st, unit=""):
  if not st:
    return "—"
  return f"{st['mean']}{unit} (p50 {st['p50']}, p95 {st['p95']}, max {st['max']}, n={st['n']})"


def render_markdown(r):
  """The archived one-pager: what the link did, and whether it passed."""
  k, a, d, w, tl = r["kernel"], r["app"], r["device"], r["window"], r["timeline"]
  L = [f"# jetlink 稳定性报表 — {w['started_at']}", "",
       f"- 窗口：{w['started_at']} 起 **{w['duration_s']} s**（label: `{r.get('label') or '-'}`）",
       f"- 链路：设备 → Jetlink App `{k.get('peer')}`（行车预览 + 手机侧大模型在线）",
       f"- 内核采样 {k.get('samples')} 次；看到的 socket：{', '.join(k.get('sockets_seen') or ['—'])}",
       f"- 设备：CPU busy {_fmt(d.get('cpu_busy_pct'), '%')}；最高温 {_fmt(d.get('max_temp_c'), ' °C')}", "",
       "## 1. 内核侧（TCP，1 Hz）", "",
       "| 指标 | 值 |", "| --- | --- |",
       f"| Send-Q 非零秒数 | {k.get('send_q_nonzero_seconds')} / {k.get('samples')} |",
       f"| Send-Q | {_fmt(k.get('send_q_total'), ' B')} |",
       f"| Send-Q > 5 KB 采样点 | {len(tl.get('send_q_spikes') or [])} |"]
  for peer, pr in (k.get("per_peer") or {}).items():
    L += [f"| RTT（{peer}） | {_fmt(pr.get('rtt_ms'), ' ms')} |",
          f"| RTT 逐秒步进（抖动） | {_fmt(pr.get('rtt_step_ms'), ' ms')} |",
          f"| RTTVAR（内核抖动估计） | {_fmt(pr.get('rttvar_ms'), ' ms')} |",
          f"| 吞吐 | {pr.get('send_mbps')} Mbps，{pr.get('acked_mb')} MB |",
          f"| 重传 | {pr.get('retrans')} |"]

  L += ["", "## 2. 应用侧（帧节拍）", "",
        "| 指标 | 值 |", "| --- | --- |",
        f"| 采样到 frame 行 | {a.get('frame_lines')} 条（frame {a.get('frame_id_first')} → {a.get('frame_id_last')}） |",
        f"| 帧率 | {a.get('fps_est')} fps |",
        f"| 帧间隔 | {_fmt(a.get('interval_ms'), ' ms')} |",
        f"| warp | {_fmt(a.get('warp_ms'), ' ms')} |",
        f"| send | {_fmt(a.get('send_ms'), ' ms')} |",
        f"| server queue | {_fmt(a.get('server_queue_ms'), ' ms')} |",
        f"| server total | {_fmt(a.get('server_total_ms'), ' ms')} |",
        f"| stage tick 间隔 | {_fmt(a.get('stage_tick_gap_ms'), ' ms')} |",
        f"| stage tick fps | {_fmt(a.get('stage_tick_fps'))} |",
        f"| 帧路径停顿（>1.5 s） | {len(a.get('stalls') or [])} 次 |",
        f"| 单帧 hiccup（send>10 ms 或 server>45 ms） | {len(a.get('hiccups') or [])} 条 |"]
  if a.get("stalls"):
    L += ["", "停顿明细："]
    L += [f"- {s['at']} 断 {s['gap_s']} s，约丢 {s['frames_skipped']} 帧" for s in a["stalls"]]
  trips = a.get("trips") or []
  if trips:
    L += ["", "trips 聚合（`held` = 回复迟到、只能沿用上一帧输出的帧；`over` = 超 20 Hz 整帧预算的帧）：", "",
          "| frames | over | held | pipelined | span s | p50 ms | p99 ms | max ms | server ms |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for t in trips:
      keys = ("frames", "over", "held", "pipe", "span", "p50", "p99", "max", "server")
      L.append("| " + " | ".join(str(t.get(k)) for k in keys) + " |")

  L += ["", "## 3. 事件", ""]
  ev = r["events"]["counts"]
  L += ["| 事件 | 次数 |", "| --- | --- |"]
  L += [f"| {name} | {n} |" for name, n in ev.items()]
  if r["events"].get("hits"):
    L += ["", "命中样例："] + [f"- {h['at']} `{h['kind']}` {h['msg']}" for h in r["events"]["hits"]]

  # the last trips line is the widest window the host itself kept: the share of
  # frames whose reply came too late is the link's own verdict on itself
  last_held = None
  if trips and trips[-1].get("frames"):
    last_held = 100.0 * (trips[-1].get("held") or 0) / trips[-1]["frames"]
  iv = a.get("interval_ms") or {}
  sd = a.get("send_ms") or {}
  tt = a.get("server_total_ms") or {}
  temps = d.get("max_temp_c") or {}
  checks = [
    ("帧率稳定在 20 fps", a.get("fps_est") is not None and 19.0 <= a["fps_est"] <= 21.0),
    ("帧间隔 p95 < 60 ms", (iv.get("p95") or 0) < 60),
    ("send p95 < 10 ms", (sd.get("p95") or 0) < 10),
    ("server total p95 < 45 ms", (tt.get("p95") or 0) < 45),
    ("无帧路径停顿", not a.get("stalls")),
    ("无丢帧事件", not ev.get("lost_frames")),
    ("无连续 hold 放弃（demote）", not ev.get("hold_gave_up") and not ev.get("demote")),
    ("迟回复帧占比 < 2%", (last_held or 0.0) < 2.0),
    ("无断链 / 重连", not ev.get("link_abandoned") and not ev.get("reconnect")),
    ("设备未过热降频（<75 °C）", (temps.get("max") or 0) < 75),
  ]
  L += ["", "## 4. 判定", "", "| 检查项 | 结果 |", "| --- | --- |"]
  L += [f"| {name} | {'PASS' if ok else 'FAIL'} |" for name, ok in checks]
  if last_held is not None:
    L += ["", f"（trip 聚合里迟回复帧占比 {last_held:.2f}%）"]
  L += ["", f"**总体：{'PASS' if all(ok for _, ok in checks) else 'FAIL'}**", ""]
  return "\n".join(L)


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--duration", type=float, default=60.0)
  ap.add_argument("--interval", type=float, default=1.0)
  ap.add_argument("--no-write", action="store_true")
  ap.add_argument("--label", default="")
  ap.add_argument("--peer", default="", help="host:port override for the capture")
  args = ap.parse_args()

  host, port = peer_from_file()
  if args.peer:
    _h, _, _p = args.peer.partition(":")
    host, port = _h or host, int(_p) if _p else port
  if not port:
    print("warning: no jetlink peer (no --peer, no " + PEER_FILE + "); falling back to sport :5090",
          file=sys.stderr)

  t0 = _wall(CLOCK_REALTIME)
  samples = []
  while _wall(CLOCK_REALTIME) - t0 < args.duration:
    s = sample_sockets(host, port)
    s["t"] = _wall(CLOCK_REALTIME)
    s["cpu"] = _proc_snapshot()
    s["temp_c"] = _max_temp()
    samples.append(s)
    time.sleep(args.interval)
  t1 = _wall(CLOCK_REALTIME)

  frames, stages, ticks, trips, others = scan_logs(t0, t1)
  event_counts, event_hits = scan_events(t0, t1)
  sys_pct, per_pct = cpu_series(samples)
  temps = [s["temp_c"] for s in samples if s.get("temp_c")]

  # -- kernel side ------------------------------------------------------------------
  send_q = [sum(x["send_q"] for x in s["sockets"]) for s in samples if s.get("sockets")]
  # per-peer series, keyed by peer address: picking "the busiest socket" each
  # second instead would interleave sockets whenever a reconnect moved the bulk
  # traffic, and invent jitter that no link had
  per_peer: dict[str, list[tuple[float, dict]]] = {}
  for s in samples:
    for x in s.get("sockets", []):
      if x.get("bytes_acked", 0) > 1e6:
        per_peer.setdefault(x["peer"], []).append((s["t"], x))
  peer_report = {}
  for peer, rows in per_peer.items():
    rtts = [x["rtt_ms"] for _, x in rows if "rtt_ms" in x]
    rt = [abs(b - a) for a, b in zip(rtts, rtts[1:], strict=False)]
    rv = [x["rttvar_ms"] for _, x in rows if "rttvar_ms" in x]
    first, last = rows[0][1], rows[-1][1]
    span = rows[-1][0] - rows[0][0]
    peer_report[peer] = {
      "samples": len(rows),
      "acked_mb": round((last.get("bytes_acked", 0) - first.get("bytes_acked", 0)) / 1e6, 2),
      "send_mbps": round(8 * (last.get("bytes_acked", 0) - first.get("bytes_acked", 0)) / max(span, 1e-9) / 1e6, 2),
      "rtt_ms": _stats(rtts),
      "rtt_step_ms": _stats(rt),
      "rttvar_ms": _stats(rv),
      "retrans": first.get("retrans", 0) if first.get("retrans", 0) == last.get("retrans", 0) else
                 [first.get("retrans", 0), last.get("retrans", 0)],
    }

  # -- application side ------------------------------------------------------------
  frames.sort(key=lambda r: r["t"])
  fps_series = []
  for a, b in zip(frames, frames[1:], strict=False):
    dt = b["t"] - a["t"]
    if dt > 0.2 and b["frame"] > a["frame"]:
      fps_series.append((b["frame"] - a["frame"]) / dt)
  interval_ms = [1000.0 / f for f in fps_series if f > 0]

  ticks.sort(key=lambda r: r["t"])
  tick_fps, tick_gaps = [], []
  for a, b in zip(ticks, ticks[1:], strict=False):
    dt = b["t"] - a["t"]
    tick_gaps.append(dt * 1000.0)
    if dt > 0 and b["frame"] > a["frame"]:
      tick_fps.append((b["frame"] - a["frame"]) / dt)
  # a 1 Hz publisher that went quiet for >1.5x its period is a stall of the frame
  # path, the thing a live preview notices first
  stalls = []
  for a, b in zip(ticks, ticks[1:], strict=False):
    if (b["t"] - a["t"]) > 1.5:
      stalls.append({"gap_s": round(b["t"] - a["t"], 2),
                     "at": time.strftime("%H:%M:%S", time.localtime(a["t"])),
                     "frames_skipped": b["frame"] - a["frame"] - 20})
  hiccups = [{"at": time.strftime("%H:%M:%S", time.localtime(f["t"])), "frame": f["frame"],
              "send_ms": f["send"], "server_total_ms": f["server_total"]}
             for f in frames if f["send"] > 10 or f["server_total"] > 45]

  timeline = [{"t": round(s["t"] - t0, 1),
               "send_q": sum(x["send_q"] for x in s.get("sockets", [])),
               "send_q_by_peer": {x["peer"]: x["send_q"] for x in s.get("sockets", [])},
               "rtt": {x["peer"]: x.get("rtt_ms") for x in s.get("sockets", []) if "rtt_ms" in x},
               "peers": [x["peer"] for x in s.get("sockets", [])]}
              for s in samples]
  sendq_spikes = [row for row in timeline if row["send_q"] > 5000]
  peer_sendq = {}
  for row in timeline:
    for peer, q in row["send_q_by_peer"].items():
      peer_sendq.setdefault(peer, []).append(q)
  first_seen = {}
  for row in timeline:
    for peer in row["peers"]:
      first_seen.setdefault(peer, row["t"])

  report = {
    "timeline": {"send_q_spikes": sendq_spikes, "peer_first_seen_s": first_seen,
                 "send_q_by_peer": {k: _stats(v) for k, v in peer_sendq.items()},
                 "peer_count_series": [len(r["peers"]) for r in timeline]},
    "device": {
      "cpu_busy_pct": _stats(sys_pct),
      "cpu_by_process_pct": {k: _stats(v) for k, v in per_pct.items()},
      "max_temp_c": _stats(temps),
    },
    "events": {"counts": event_counts, "hits": event_hits},
    "label": args.label,
    "window": {"start": t0, "end": t1, "duration_s": round(t1 - t0, 1),
               "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0))},
    "kernel": {
      "samples": len(samples),
      "peer": f"{host}:{port}" if port else None,
      "sockets_seen": sorted({x["peer"] for s in samples for x in s.get("sockets", [])}),
      "send_q_total": _stats(send_q),
      "send_q_nonzero_seconds": sum(1 for v in send_q if v > 0),
      "per_peer": peer_report,
    },
    "app": {
      "frame_lines": len(frames),
      "frame_id_first": frames[0]["frame"] if frames else None,
      "frame_id_last": frames[-1]["frame"] if frames else None,
      "fps_est": round((frames[-1]["frame"] - frames[0]["frame"]) / (frames[-1]["t"] - frames[0]["t"]), 2) if len(frames) > 1 else None,
      "interval_ms": _stats(interval_ms),
      "send_ms": _stats([f["send"] for f in frames]),
      "warp_ms": _stats([f["warp"] for f in frames]),
      "server_queue_ms": _stats([f["server_queue"] for f in frames]),
      "server_total_ms": _stats([f["server_total"] for f in frames]),
      "stage_ticks": len(ticks),
      "stage_tick_fps": _stats(tick_fps),
      "stage_tick_gap_ms": _stats(tick_gaps),
      "stalls": stalls,
      "hiccups": hiccups[-12:],
      "stages": stages,
      "trips": trips,
      "other_lines": others[-12:],
    },
  }

  ts = time.strftime("%Y%m%d-%H%M%S", time.localtime(t0))
  print(json.dumps(report, indent=2, ensure_ascii=False))
  if not args.no_write:
    os.makedirs("artifacts", exist_ok=True)
    jpath = f"artifacts/jetlink_stability_{ts}.json"
    with open(jpath, "w") as fh:
      json.dump(report, fh, indent=2, ensure_ascii=False)
    mpath = f"ai/docs/jetlink_stability_{ts}.md"
    os.makedirs(os.path.dirname(mpath), exist_ok=True)
    with open(mpath, "w") as fh:
      fh.write(render_markdown(report))
    print(f"\nwrote {jpath}\nwrote {mpath}", file=sys.stderr)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
