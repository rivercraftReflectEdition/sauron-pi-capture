# pi-capture — Sauron-1 night-sky data acquisition

Field capture tool for the in-house Sauron-1 star tracker. Runs on a
**Raspberry Pi 5** with a **Sony IMX296 global-shutter camera** and records RAW
(DNG) frames plus the per-frame quantifiers the algorithm side needs: exposure
time (shutter speed), gain, sensor timestamp, and a UTC stamp.

This is the data-collection half of the "Night-sky capture, catalog solve"
validation step in `../STAR_TRACKER_FRIDAY_REVIEW_PLAN.md`.

## What it produces

```
data/session_YYYYmmdd_HHMMSS/
├── session.json     # camera, mode, lens, site, clock reference (BOOTTIME<->UTC)
├── frames.csv       # one row per frame: exposure, gain, timestamps, temp...
├── raw/000000.dng   # linear RAW science frames (no gamma/denoise/AWB)
└── preview/*.jpg     # occasional ISP quicklook JPEGs (eyeballing only)
```

The **DNG is the science data**. The JPEGs are just so you can confirm in the
field that stars are landing on the sensor.

## One-time Pi setup

```bash
# Raspberry Pi OS (Bookworm) — picamera2 ships via apt, do NOT pip install it
sudo apt update
sudo apt install -y python3-picamera2 git

# Confirm the camera is detected (you want to see 'imx296')
rpicam-hello --list-cameras
```

If it is *not* detected, add the overlay and reboot:

```bash
# /boot/firmware/config.txt
camera_auto_detect=0
dtoverlay=imx296          # add ,mono ONLY if your module is the mono variant and the
                          #   driver build supports it — verify with --list-cameras
```

`quicklook.py` analysis deps are separate and pip-installable:

```bash
pip install --break-system-packages rawpy numpy pillow scipy
```

## Capture

```bash
# First: see what the camera reports (modes, exposure limits)
python3 capture.py --list-modes

# A 60 s burst at a fixed setting (refine exposure/gain from a bracket first)
python3 capture.py --duration 60 --exposure-us 200000 --gain 4.0 \
    --focus-note "infinity sharp" --operator river

# Exposure sweep (steps derived from the f/1.4 photon model; 10 ms = flight point)
# — the right first move in the field. See FIELD_NOTES.md for the derivation.
python3 capture.py --duration 90 \
    --bracket "5000:2,10000:2,20000:2,50000:2,100000:2,200000:2,500000:2,1000000:2" \
    --frames-per-setting 5
```

Key flags (`--help` for all):

| flag | meaning |
|---|---|
| `--duration` | seconds to capture |
| `--exposure-us` | shutter speed, microseconds (fixed mode) |
| `--gain` | analogue gain (fixed mode) |
| `--bracket` | `exp_us:gain` pairs, swept repeatedly |
| `--frames-per-setting` | frames per bracket step |
| `--preview-every` | seconds between quicklook JPEGs (0 = none) |
| `--focus-note` | logged verbatim into session.json |

Exposure and gain are **clamped to the camera's reported limits** at runtime, so
you cannot silently ask for an impossible shutter. The actually-applied values
are what get logged (read back from frame metadata), not what you requested.

## Auto-start on boot (headless, no screen)

For unattended field use, install the systemd service once (at home, on network):

```bash
./field/install-service.sh
```

The Pi then starts capturing automatically ~20–40 s after it gets power — no
login or screen needed. Capture settings live in `startracker.conf` on the SD
card's boot partition, editable from any laptop. Details, plus the **clock
(RTC battery)** and **focus** caveats, are in `FIELD_NOTES.md`.

## Quicklook (is the data any good?)

```bash
python3 quicklook.py data/session_*/raw/000010.dng
```

Prints background/noise, peak SNR, a rough star count, and the brightest star's
**FWHM in pixels** — the number that tells you if you are sampled well enough for
sub-pixel centroiding (target ~1.5–2.5 px). See `FIELD_NOTES.md` for why.

## Make it a repo / clone on the Pi

```bash
# here on the workstation
cd pi-capture
git init && git add . && git commit -m "initial field capture tool"
# push to GitHub, then on the Pi:
git clone <your-repo-url> && cd pi-capture
```

`data/` is gitignored — frames stay on the SD card, code stays in git.

## Timestamps

`session.json` records the BOOTTIME↔UTC offset so every frame's
`SensorTimestamp` (libcamera CLOCK_BOOTTIME, ns) maps to real UTC:

```
frame_utc = SensorTimestamp_ns / 1e9 + utc_minus_boottime_s
```

**Sync the Pi's clock before you leave** (`chrony`/NTP on Wi-Fi), or the UTC
column is only as good as the Pi's RTC. For real plate-solve time accuracy at a
dark site with no network, log GPS time alongside, or set the clock right before
heading out. See `FIELD_NOTES.md`.
