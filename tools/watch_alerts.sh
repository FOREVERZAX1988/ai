#!/bin/bash
# Poll the comma device for new diag_watchd snapshots.
#
# Meant to be called by a scheduler on the laptop. It prints one of:
#   DEVICE_UNREACHABLE   the car is out of range (no SSH path) -> caller stops
#   NO_EVENTS_YET        the device has never recorded anything
#   BASELINE_SET         first run, existing history adopted
#   NO_NEW_EVENTS        nothing new since last call
#   === NEW EVENTS ===   one or more new index lines, followed by the snapshots
#
# Keeping the "is there news" decision in here (with a local state file) means a
# scheduled call that finds nothing costs one SSH round-trip and a few tokens.
#
# Reboot-safe by design: the state lives next to the project (not /tmp, which
# macOS reaps), and the device is found by mDNS name first -- the home LAN, the
# car CPE and a phone hotspot all hand out different subnets, and the home LAN
# itself has moved twice (192.168.1.x -> 192.168.10.x). A stale last-good
# address is tried first only because it is free to try.

set -u
export LC_ALL=C

KEY="$HOME/.ssh/id_ed25519_device"
STATE_DIR="/Users/zzz/Desktop/.workbuddy/state/comma_diag_watch"
mkdir -p "$STATE_DIR"
STATE="$STATE_DIR/last_index"
LAST_IP_FILE="$STATE_DIR/last_ip"
NOW="$STATE_DIR/index.now"

SSH_OPTS=(-i "$KEY" -o ConnectTimeout=4 -o StrictHostKeyChecking=no -o BatchMode=yes)

# The device's mDNS name (hostname == comma-<hardware id>; checked 2026-11-18 on
# the device itself). Works on any LAN that forwards multicast, which is every
# network it has been on so far.
MDNS="comma-a821bfb2.local"

# Subnets seen so far: home LAN (current, 2026-11-18), home LAN (older), the R3G
# CPE in the car, and a phone hotspot.
CANDS="192.168.10.79 192.168.1.9 192.168.7.196 192.168.43.60"

probe() {
  [ -n "$1" ] || return 1
  ssh "${SSH_OPTS[@]}" "comma@$1" true 2>/dev/null
}

DEV=""

# 1. last known good address, 2. mDNS name, 3. the candidate list. The mDNS name
# is what makes this work after the car has been somewhere new.
[ -f "$LAST_IP_FILE" ] && { CACHED=$(cat "$LAST_IP_FILE" 2>/dev/null); probe "$CACHED" && DEV="$CACHED"; }

if [ -z "$DEV" ] && probe "$MDNS"; then
  DEV="$MDNS"
fi

if [ -z "$DEV" ]; then
  for ip in $CANDS; do
    if probe "$ip"; then
      DEV="$ip"
      break
    fi
  done
fi

if [ -z "$DEV" ]; then
  echo "DEVICE_UNREACHABLE"
  exit 0
fi

echo "$DEV" > "$LAST_IP_FILE"
echo "device=$DEV"

ssh -i "$KEY" -o ConnectTimeout=5 -o StrictHostKeyChecking=no \
  "comma@$DEV" 'tail -60 /data/diag_events/index.log 2>/dev/null' > "$NOW" 2>/dev/null

if [ ! -s "$NOW" ]; then
  echo "NO_EVENTS_YET"
  exit 0
fi

if [ ! -f "$STATE" ]; then
  cp "$NOW" "$STATE"
  # Do not swallow the first sighting: print what is already there so the caller
  # can tell a stale history from an alert that just fired.
  echo "BASELINE_SET lines=$(wc -l < "$STATE" | tr -d ' ') recent:"
  tail -5 "$NOW"
  exit 0
fi

NEW=$(grep -Fxv -f "$STATE" "$NOW" 2>/dev/null | grep -v '^$' || true)
cp "$NOW" "$STATE"

if [ -z "$NEW" ]; then
  echo "NO_NEW_EVENTS"
  exit 0
fi

echo "=== NEW EVENTS ==="
echo "$NEW"
echo "=== SNAPSHOT (newest first) ==="
ssh -i "$KEY" -o ConnectTimeout=5 -o StrictHostKeyChecking=no "comma@$DEV" \
  'for f in $(ls -t /data/diag_events/*.json 2>/dev/null | head -3); do echo "--- $f"; cat "$f"; done' 2>/dev/null |
  head -260
