#!/usr/bin/env bash
# Materialise the substitute ONNX weights the neural-signal sim needs.
#
# tools/signal_analysis/sim_neural_on_c3.py hardcodes
#   /data/tmp/sub_detector.onnx  /data/tmp/sub_classifier.onnx
# but /data/tmp is scratch space: a reboot empties it. 2026-10-22 08:10 that is
# exactly how the sim broke (FileNotFoundError: /data/tmp/sub_detector.onnx)
# after a manual device reboot. So the weights live in /data/.sim_assets
# (persistent, same disk as /data/.pydeps) and are copied into /data/tmp on
# demand; they are regenerated only when the persistent copy is gone.
#
# Usage:  bash ai/scripts/ensure_sim_assets.sh && cd /data/openpilot \
#           && python3 tools/signal_analysis/sim_neural_on_c3.py
set -euo pipefail

ASSETS=/data/.sim_assets
SCRATCH=/data/tmp
OPENPILOT=${OPENPILOT_ROOT:-/data/openpilot}
FILES="sub_detector.onnx sub_classifier.onnx"

mkdir -p "$ASSETS" "$SCRATCH"

missing=0
for f in $FILES; do [ -s "$ASSETS/$f" ] || missing=1; done
if [ "$missing" -eq 1 ]; then
  echo "[sim-assets] persistent copy incomplete -> regenerating into $ASSETS"
  # make_substitute_models.py takes the two output paths as argv (a bare call is
  # an IndexError, which is what the recipe used to tell you to run).
  ( cd "$OPENPILOT" && python3 tools/signal_analysis/make_substitute_models.py \
      "$ASSETS/sub_detector.onnx" "$ASSETS/sub_classifier.onnx" )
fi

for f in $FILES; do
  cmp -s "$ASSETS/$f" "$SCRATCH/$f" || cp -f "$ASSETS/$f" "$SCRATCH/$f"
done

echo "[sim-assets] ready in $SCRATCH:"
( cd "$SCRATCH" && sha256sum $FILES )
