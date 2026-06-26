#!/usr/bin/env bash
# Launcher used by the systemd service (startracker.service).
#
# It reads an optional config file from the SD card's BOOT partition -- which
# you can edit from any laptop (Windows/Mac) without a screen or SSH -- then
# waits for the camera to enumerate and starts capture.py.
#
# Config search order (first match wins):
#   /boot/firmware/startracker.conf   <- edit this from a laptop
#   /boot/startracker.conf
#   <repo>/field/startracker.conf
# If none exist, the defaults below are used.
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3}"

# ---- defaults (overridden by config file) -------------------------------- #
DURATION=999999            # seconds; huge = run until power off or disk full
MODE=fixed                 # fixed | bracket
EXPOSURE_US=200000         # 0.2 s
GAIN=4.0
BRACKET="20000:1,50000:2,100000:4,200000:8,500000:12"
FRAMES_PER_SETTING=5
PREVIEW_EVERY=5
MIN_FREE_GB=1.0
OUT="$REPO/data"
FOCUS_NOTE=""
NOTE="auto-boot capture"
EXTRA_ARGS=""

# ---- load config if present ---------------------------------------------- #
for cfg in /boot/firmware/startracker.conf /boot/startracker.conf "$REPO/field/startracker.conf"; do
  if [ -f "$cfg" ]; then
    echo "[run-capture] loading config: $cfg"
    # shellcheck disable=SC1090
    . "$cfg"
    break
  fi
done

# ---- wait for the camera to enumerate (up to ~60 s) ---------------------- #
echo "[run-capture] waiting for camera..."
for _ in $(seq 1 30); do
  if rpicam-hello --list-cameras 2>/dev/null | grep -qi imx296; then
    echo "[run-capture] camera detected"
    break
  fi
  sleep 2
done

# ---- build args ---------------------------------------------------------- #
ARGS=(--duration "$DURATION" --out "$OUT" --min-free-gb "$MIN_FREE_GB"
      --preview-every "$PREVIEW_EVERY")
if [ "$MODE" = "bracket" ]; then
  ARGS+=(--bracket "$BRACKET" --frames-per-setting "$FRAMES_PER_SETTING")
else
  ARGS+=(--exposure-us "$EXPOSURE_US" --gain "$GAIN")
fi
[ -n "$FOCUS_NOTE" ] && ARGS+=(--focus-note "$FOCUS_NOTE")
[ -n "$NOTE" ] && ARGS+=(--note "$NOTE")

echo "[run-capture] starting: $PY capture.py ${ARGS[*]} $EXTRA_ARGS"
cd "$REPO"
# shellcheck disable=SC2086
exec "$PY" capture.py "${ARGS[@]}" $EXTRA_ARGS
