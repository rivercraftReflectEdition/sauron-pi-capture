#!/usr/bin/env bash
# selftest.sh -- one-shot "is the rig working?" check.
#
#   1. confirms the IMX296 is detected
#   2. shows a 30 s live preview at the configured shutter/gain (SET FOCUS HERE)
#   3. captures 5 s of data with the SAME settings the boot service will use
#   4. verifies the frames + logged metadata and prints PASS / FAIL
#
# Run from the repo root:
#   ./selftest.sh                 full test
#   ./selftest.sh --no-preview    skip the 30 s preview window (headless)
set -u

REPO="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-python3}"
PREVIEW_SECONDS=30
CAPTURE_SECONDS=5
DO_PREVIEW=1
[ "${1:-}" = "--no-preview" ] && DO_PREVIEW=0

# ---- settings: reuse the boot config so we test what we fly --------------- #
EXPOSURE_US=10000
GAIN=2.0
for cfg in /boot/firmware/startracker.conf /boot/startracker.conf "$REPO/field/startracker.conf"; do
  if [ -f "$cfg" ]; then echo "[selftest] settings from $cfg"; . "$cfg"; break; fi
done
echo "[selftest] testing exposure=${EXPOSURE_US}us gain=${GAIN}"

fail() { echo; echo "RESULT: FAIL -- $1"; exit 1; }

# ---- 1. camera present ---------------------------------------------------- #
echo; echo "== 1/4 camera detection =="
if ! rpicam-hello --list-cameras 2>/dev/null | grep -qi imx296; then
  fail "imx296 not detected (rpicam-hello --list-cameras)"
fi
echo "  OK: imx296 detected"

# ---- 2. preview ----------------------------------------------------------- #
echo; echo "== 2/4 live preview (${PREVIEW_SECONDS}s) -- aim + set focus now =="
if [ "$DO_PREVIEW" = 1 ]; then
  if [ -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]; then
    rpicam-hello -t $((PREVIEW_SECONDS*1000)) --shutter "$EXPOSURE_US" --gain "$GAIN" \
      || echo "  (preview exited early -- continuing)"
  else
    echo "  No display (SSH?). Streaming ${PREVIEW_SECONDS}s headless to prove the"
    echo "  pipeline; attach a monitor on the Pi to actually SEE the preview."
    rpicam-hello -t $((PREVIEW_SECONDS*1000)) --nopreview \
      --shutter "$EXPOSURE_US" --gain "$GAIN" >/dev/null 2>&1 \
      || fail "camera failed to stream"
  fi
  echo "  OK: preview/stream done"
else
  echo "  skipped (--no-preview)"
fi

# ---- 3. capture ----------------------------------------------------------- #
echo; echo "== 3/4 capture (${CAPTURE_SECONDS}s) =="
OUT="$REPO/data"
"$PY" "$REPO/capture.py" --duration "$CAPTURE_SECONDS" --exposure-us "$EXPOSURE_US" \
  --gain "$GAIN" --out "$OUT" --preview-every 1 --note "selftest" \
  || fail "capture.py errored"

SESS="$(ls -dt "$OUT"/session_* 2>/dev/null | head -1)"
[ -n "$SESS" ] || fail "no session folder was created"
echo "  session: $SESS"

# ---- 4. verify ------------------------------------------------------------ #
echo; echo "== 4/4 verify =="
NDNG=$(find "$SESS/raw" -name '*.dng' 2>/dev/null | wc -l | tr -d ' ')
NJPG=$(find "$SESS/preview" -name '*.jpg' 2>/dev/null | wc -l | tr -d ' ')
CSV="$SESS/frames.csv"
[ -f "$CSV" ] || fail "frames.csv missing"
[ "$NDNG" -gt 0 ] || fail "no DNG frames were written"

# mean actual exposure_us (col 8) and analogue gain (col 9) over data rows
read -r MEAN_EXP MEAN_GAIN NROWS < <(
  awk -F, 'NR>1 && $8!="" {e+=$8; g+=$9; n++}
           END{if(n>0) printf "%.0f %.2f %d", e/n, g/n, n; else printf "0 0 0"}' "$CSV")
echo "  DNG frames    : $NDNG"
echo "  preview JPEGs : $NJPG"
echo "  CSV data rows : $NROWS"
echo "  mean exposure : ${MEAN_EXP}us (requested ${EXPOSURE_US})"
echo "  mean gain     : ${MEAN_GAIN} (requested ${GAIN})"

[ "$NROWS" -gt 0 ] || fail "frames.csv has no data rows"
awk -v a="$MEAN_EXP" -v b="$EXPOSURE_US" \
  'BEGIN{d=a-b; if(d<0)d=-d; exit !(b>0 && d/b<=0.25)}' \
  || fail "logged exposure ${MEAN_EXP}us is >25% off requested ${EXPOSURE_US}us"

echo
echo "RESULT: PASS -- $NDNG frames at ~${MEAN_EXP}us, metadata verified."
echo "Data: $SESS"
echo "(quick visual: python3 quicklook.py $SESS/raw/000000.dng)"
