#!/usr/bin/env python3
"""
Sauron-1 star-tracker field capture
====================================

Captures RAW (DNG) frames from a Sony IMX296 global-shutter camera on a
Raspberry Pi 5 and logs the per-frame quantifiers a star-tracker pipeline
needs: exposure time (shutter speed), analogue/digital gain, the sensor
timestamp, and a UTC wall-clock stamp for every frame.

Why it is built this way (so future-you trusts the data):

  * RAW science data only. We save DNG (linear counts, no gamma / denoise /
    white balance / sharpening) because centroiding + plate solving needs the
    un-cooked photon counts. The optional JPEG is for human eyeballing only.
  * Manual everything. Auto-exposure, auto-gain and AWB are turned OFF so every
    frame in the set has a known, logged radiometric state.
  * FrameDurationLimits is opened up to the exposure time. If you do not do
    this the default frame-rate cap silently clamps long exposures, and you
    quietly get a shorter shutter than you asked for.
  * Sensor limits are read from the camera at runtime (camera_controls) and the
    requested exposure/gain are clamped to them -- we never hard-code a wrong
    sensor limit.
  * Timestamps: libcamera's SensorTimestamp is CLOCK_BOOTTIME nanoseconds. We
    record the BOOTTIME<->UTC offset once at start (and again at end) so every
    frame can be placed on a real UTC timeline for later sky correlation.

Examples:
  python3 capture.py --list-modes
  python3 capture.py --duration 60 --exposure-us 200000 --gain 4.0
  python3 capture.py --duration 90 \
      --bracket "20000:1,50000:2,100000:4,200000:8,500000:12" \
      --frames-per-setting 5 --focus-note "infinity, sharp"

See FIELD_NOTES.md for the observing checklist and the defocus rationale.
"""

import argparse
import csv
import json
import os
import shutil
import signal
import sys
import time
from datetime import datetime, timezone


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def parse_bracket(spec):
    """Parse '20000:1,100000:4' -> [(20000, 1.0), (100000, 4.0)]."""
    settings = []
    for pair in spec.split(","):
        pair = pair.strip()
        if not pair:
            continue
        exp_str, _, gain_str = pair.partition(":")
        if not gain_str:
            raise ValueError(f"bracket entry '{pair}' must be exposure_us:gain")
        settings.append((int(float(exp_str)), float(gain_str)))
    if not settings:
        raise ValueError("empty --bracket")
    return settings


def pick_raw_mode(sensor_modes):
    """Pick the highest-bit-depth, largest-area raw sensor mode."""
    def score(m):
        w, h = m["size"]
        return (m.get("bit_depth", 0), w * h)
    return max(sensor_modes, key=score)


def utc_iso(unix_seconds):
    return datetime.fromtimestamp(unix_seconds, tz=timezone.utc).isoformat()


def free_gb(path):
    return shutil.disk_usage(path).free / 1e9


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(
        description="Star-tracker RAW field capture for IMX296 on Raspberry Pi 5",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--out", default="data", help="base output directory")
    ap.add_argument("--camera-num", type=int, default=0,
                    help="camera index (CAM/DISP 0 is usually 0)")
    ap.add_argument("--duration", type=float, default=60.0,
                    help="capture duration in seconds")
    ap.add_argument("--max-frames", type=int, default=0,
                    help="stop after N frames (0 = no limit, use --duration)")

    # Fixed-setting mode
    ap.add_argument("--exposure-us", type=int, default=200000,
                    help="shutter speed in microseconds (fixed mode)")
    ap.add_argument("--gain", type=float, default=4.0,
                    help="analogue gain (fixed mode)")

    # Bracket / sweep mode
    ap.add_argument("--bracket", default="",
                    help="exposure:gain pairs, e.g. '50000:2,200000:8'. "
                         "If set, overrides --exposure-us/--gain and sweeps.")
    ap.add_argument("--frames-per-setting", type=int, default=5,
                    help="frames captured per bracket setting")
    ap.add_argument("--settle-frames", type=int, default=2,
                    help="frames discarded after a setting change to let "
                         "exposure/gain take effect")

    # Preview + housekeeping
    ap.add_argument("--preview-every", type=float, default=2.0,
                    help="save a JPEG quicklook this often (s); 0 disables")
    ap.add_argument("--min-free-gb", type=float, default=0.5,
                    help="stop when free disk falls below this")
    ap.add_argument("--no-dng", action="store_true",
                    help="skip DNG (debug only -- you lose the science data)")

    # Logbook metadata (free text -> session.json)
    ap.add_argument("--site", default="Joshua Tree, CA")
    ap.add_argument("--lens", default="25 mm f/1.4 C-mount")
    ap.add_argument("--focus-note", default="",
                    help="e.g. 'infinity sharp' or 'defocused ~2.5 px'")
    ap.add_argument("--operator", default="")
    ap.add_argument("--note", default="", help="free-form session note")

    ap.add_argument("--list-modes", action="store_true",
                    help="print camera info and exit")
    args = ap.parse_args()

    # Import here so --help works on a machine without picamera2 installed.
    try:
        from picamera2 import Picamera2
    except ImportError:
        sys.exit("picamera2 not found. On Raspberry Pi OS: "
                 "sudo apt install -y python3-picamera2")

    picam2 = Picamera2(camera_num=args.camera_num)

    # ----- camera info ----------------------------------------------------- #
    print("Camera:", picam2.camera_properties.get("Model", "unknown"))
    print("Sensor resolution:", picam2.sensor_resolution)
    print("Raw sensor modes:")
    for m in picam2.sensor_modes:
        print(f"  size={m['size']} format={m.get('format')} "
              f"bit_depth={m.get('bit_depth')} fps<= {m.get('fps')} "
              f"exposure_limits_us={m.get('exposure_limits')}")
    if args.list_modes:
        picam2.close()
        return

    raw_mode = pick_raw_mode(picam2.sensor_modes)
    print(f"\nUsing raw mode: size={raw_mode['size']} "
          f"format={raw_mode['format']} bit_depth={raw_mode.get('bit_depth')}")

    # Small ISP preview stream alongside full-res raw (same underlying frame).
    pw = max(320, raw_mode["size"][0] // 2)
    ph = max(240, raw_mode["size"][1] // 2)

    config = picam2.create_still_configuration(
        raw={"size": raw_mode["size"], "format": raw_mode["format"]},
        main={"size": (pw, ph)},
        buffer_count=6,
        controls={"AeEnable": False, "AwbEnable": False},
    )
    picam2.configure(config)

    # Authoritative runtime limits (after configure).
    exp_min, exp_max, _ = picam2.camera_controls["ExposureTime"]
    gain_min, gain_max, _ = picam2.camera_controls["AnalogueGain"]
    print(f"ExposureTime limits: {exp_min}..{exp_max} us")
    print(f"AnalogueGain limits: {gain_min}..{gain_max}")

    def clamp_setting(exp, gain):
        c_exp = int(min(max(exp, exp_min), exp_max))
        c_gain = float(min(max(gain, gain_min), gain_max))
        if c_exp != exp:
            print(f"  ! exposure {exp} us clamped to {c_exp} us")
        if abs(c_gain - gain) > 1e-6:
            print(f"  ! gain {gain} clamped to {c_gain}")
        return c_exp, c_gain

    # Build the list of (exposure, gain) settings.
    if args.bracket:
        settings = [clamp_setting(e, g) for e, g in parse_bracket(args.bracket)]
        mode_name = "bracket"
    else:
        settings = [clamp_setting(args.exposure_us, args.gain)]
        mode_name = "fixed"
    print(f"Mode: {mode_name}; settings (exp_us, gain): {settings}")

    # ----- output folders -------------------------------------------------- #
    # Wall clock is untrusted in the field (no RTC/network): a repeated boot
    # time can reproduce an old stamp, so claim the dir exclusively and add a
    # suffix on collision instead of silently reusing it (exist_ok would let
    # frame 000000 overwrite a previous session).
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(args.out, exist_ok=True)
    for attempt in range(100):
        suffix = "" if attempt == 0 else f"_{attempt:02d}"
        session_dir = os.path.join(args.out, f"session_{stamp}{suffix}")
        try:
            os.mkdir(session_dir)
            break
        except FileExistsError:
            continue
    else:
        raise RuntimeError(f"could not create a unique session dir under {args.out}")
    raw_dir = os.path.join(session_dir, "raw")
    prev_dir = os.path.join(session_dir, "preview")
    os.makedirs(raw_dir)
    os.makedirs(prev_dir)
    print(f"\nWriting to: {session_dir}")
    print(f"Free disk: {free_gb(session_dir):.1f} GB\n")

    # ----- clock reference: BOOTTIME (sensor clock) <-> UTC ---------------- #
    def clock_refs():
        boottime = time.clock_gettime(time.CLOCK_BOOTTIME)
        utc = time.time()
        return boottime, utc

    boottime_ref, utc_ref = clock_refs()
    utc_minus_boot = utc_ref - boottime_ref  # add to (SensorTimestamp/1e9)

    session = {
        "schema": "sauron1-capture/1",
        "session_dir": session_dir,
        "start_utc": utc_iso(utc_ref),
        "site": args.site,
        "lens": args.lens,
        "focus_note": args.focus_note,
        "operator": args.operator,
        "note": args.note,
        "camera_model": picam2.camera_properties.get("Model", "unknown"),
        "camera_num": args.camera_num,
        "sensor_resolution": [int(x) for x in picam2.sensor_resolution],
        "raw_mode": {"size": [int(x) for x in raw_mode["size"]],
                     "format": str(raw_mode["format"]),
                     "bit_depth": raw_mode.get("bit_depth")},
        "exposure_limits_us": [exp_min, exp_max],
        "gain_limits": [gain_min, gain_max],
        "mode": mode_name,
        "settings_exp_gain": settings,
        "frames_per_setting": args.frames_per_setting,
        "clock_ref": {"boottime_s": boottime_ref, "utc_s": utc_ref,
                      "utc_minus_boottime_s": utc_minus_boot,
                      "note": "frame_utc = SensorTimestamp_ns/1e9 + utc_minus_boottime_s"},
    }
    with open(os.path.join(session_dir, "session.json"), "w") as f:
        json.dump(session, f, indent=2)

    # ----- per-frame CSV log ----------------------------------------------- #
    csv_path = os.path.join(session_dir, "frames.csv")
    csv_file = open(csv_path, "w", newline="")
    cols = ["frame_idx", "dng", "preview", "frame_utc_iso", "frame_utc_unix",
            "host_utc_unix", "sensor_timestamp_ns", "exposure_us",
            "analogue_gain", "digital_gain", "frame_duration_us",
            "sensor_temperature_c", "req_exposure_us", "req_gain"]
    writer = csv.DictWriter(csv_file, fieldnames=cols)
    writer.writeheader()

    # ----- capture --------------------------------------------------------- #
    stop = {"flag": False}

    def handle_sigint(signum, frame):
        print("\nStopping (signal received)...")
        stop["flag"] = True
    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)

    picam2.start()

    def apply_setting(exp, gain):
        fd = int(exp + 10000)  # frame duration must exceed exposure
        picam2.set_controls({"ExposureTime": int(exp),
                             "AnalogueGain": float(gain),
                             "FrameDurationLimits": (fd, fd)})
        for _ in range(max(0, args.settle_frames)):
            req = picam2.capture_request()
            req.release()

    t0 = time.time()
    last_preview = 0.0
    frame_idx = 0

    def time_left():
        return args.duration - (time.time() - t0)

    def frames_left():
        return args.max_frames == 0 or frame_idx < args.max_frames

    def capture_one(req_exp, req_gain):
        nonlocal frame_idx, last_preview
        request = picam2.capture_request()
        host_utc = time.time()
        try:
            meta = request.get_metadata()
            base = f"{frame_idx:06d}"
            dng_name = ""
            if not args.no_dng:
                dng_name = f"{base}.dng"
                request.save_dng(os.path.join(raw_dir, dng_name))

            prev_name = ""
            now = time.time()
            if args.preview_every > 0 and (now - last_preview) >= args.preview_every:
                prev_name = f"{base}.jpg"
                try:
                    request.save("main", os.path.join(prev_dir, prev_name))
                    last_preview = now
                except Exception as e:  # preview is non-critical
                    prev_name = ""
                    print(f"  (preview save failed: {e})")
        finally:
            request.release()

        sensor_ts_ns = meta.get("SensorTimestamp", 0)
        frame_utc_unix = sensor_ts_ns / 1e9 + utc_minus_boot if sensor_ts_ns else host_utc
        writer.writerow({
            "frame_idx": frame_idx,
            "dng": dng_name,
            "preview": prev_name,
            "frame_utc_iso": utc_iso(frame_utc_unix),
            "frame_utc_unix": f"{frame_utc_unix:.6f}",
            "host_utc_unix": f"{host_utc:.6f}",
            "sensor_timestamp_ns": sensor_ts_ns,
            "exposure_us": meta.get("ExposureTime", ""),
            "analogue_gain": meta.get("AnalogueGain", ""),
            "digital_gain": meta.get("DigitalGain", ""),
            "frame_duration_us": meta.get("FrameDuration", ""),
            "sensor_temperature_c": meta.get("SensorTemperature", ""),
            "req_exposure_us": req_exp,
            "req_gain": req_gain,
        })
        csv_file.flush()  # survive a yanked power cable in the field
        frame_idx += 1

    print("Capturing. Ctrl-C to stop early.\n")
    try:
        if mode_name == "fixed":
            exp, gain = settings[0]
            apply_setting(exp, gain)
            while not stop["flag"] and time_left() > 0 and frames_left():
                if free_gb(session_dir) < args.min_free_gb:
                    print("\nLow disk space, stopping.")
                    break
                capture_one(exp, gain)
                elapsed = time.time() - t0
                fps = frame_idx / elapsed if elapsed > 0 else 0
                sys.stdout.write(
                    f"\rframes={frame_idx} elapsed={elapsed:5.1f}s "
                    f"fps={fps:4.1f} free={free_gb(session_dir):5.1f}GB ")
                sys.stdout.flush()
        else:  # bracket sweep, cycled until duration/frames hit
            si = 0
            while not stop["flag"] and time_left() > 0 and frames_left():
                if free_gb(session_dir) < args.min_free_gb:
                    print("\nLow disk space, stopping.")
                    break
                exp, gain = settings[si % len(settings)]
                apply_setting(exp, gain)
                for _ in range(args.frames_per_setting):
                    if stop["flag"] or time_left() <= 0 or not frames_left():
                        break
                    capture_one(exp, gain)
                    elapsed = time.time() - t0
                    sys.stdout.write(
                        f"\rframes={frame_idx} set=({exp}us,g{gain}) "
                        f"elapsed={elapsed:5.1f}s free={free_gb(session_dir):5.1f}GB ")
                    sys.stdout.flush()
                si += 1
    finally:
        boottime_end, utc_end = clock_refs()
        session["end_utc"] = utc_iso(utc_end)
        session["frames_captured"] = frame_idx
        session["clock_ref_end"] = {"boottime_s": boottime_end, "utc_s": utc_end}
        with open(os.path.join(session_dir, "session.json"), "w") as f:
            json.dump(session, f, indent=2)
        csv_file.close()
        picam2.stop()
        picam2.close()

    print(f"\n\nDone. {frame_idx} frames -> {session_dir}")
    print(f"Log: {csv_path}")


if __name__ == "__main__":
    main()
