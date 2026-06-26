# Joshua Tree field notes — Sauron-1 night-sky capture

Observing checklist + the engineering reasoning behind the settings. Numbers use
the locked baseline: IMX296 mono, `p = 3.45 µm`, `f = 25 mm`, `f/1.4`
(`D = f/N = 17.86 mm`), consistent with `../STAR_TRACKER_SOURCE_OF_TRUTH.md`.

Plate scale (sanity, matches the optical notebook):
```
IFOV = p / f = 3.45e-3 / 25 = 1.380e-4 rad = 28.46 arcsec/px
FOV  = 1456 px × 28.46" = 11.5°   ×   1088 px × 28.46" = 8.6°   ✓
```

---

## Should I defocus the lens for this test? — Yes, slightly. And capture both.

**Short answer:** focus sharply first and grab a set, then back the focus off a
hair to spread a bright star to ~2–3 px across (FWHM ≈ 1.5–2.5 px) and grab a
second set. Use `quicklook.py` to read the FWHM and pick. Capturing both is the
rigorous move — it directly produces the centroid-vs-defocus data the algorithm
track needs.

**Why a focused star is bad for a star tracker.** A star is a point source, so
in perfect focus the spot size is set by diffraction:

```
Airy core FWHM ≈ 1.025 · λ · N = 1.025 × 0.55 µm × 1.4 = 0.79 µm = 0.23 px
Airy first-null diameter = 2.44 · λ · N = 1.88 µm = 0.55 px
```

That is **badly undersampled** — essentially all the light lands in one pixel.
You then cannot interpolate a sub-pixel position: the centroid quantizes to the
pixel center, giving an error floor of about `pixel/√12 ≈ 0.29 px`
(≈ 8 arcsec here) plus a systematic "pixel-locking" S-curve bias. That alone
would blow the 7-arcsec cross-boresight target.

**Why spreading the PSF fixes it.** The source-of-truth centroid model is
```
σ_centroid_px ≈ σ_PSF_px / SNR
```
This assumes the PSF is sampled across several pixels so the intensity profile
can be interpolated. Deliberately defocusing (the standard star-tracker trick,
Liebe 2002 — already a core ref in the SoT) puts the PSF FWHM near Nyquist
(~1.5–2 px), where centroiding reaches ~1/10 px. Too sharp → undersampled
(above). Too blurry → photons spread out, peak SNR drops, fewer stars clear the
detection threshold, limiting magnitude and `√N_stars` both suffer. There is an
optimum, and it is a *slight* defocus.

**How much defocus is "slight"?** Geometric blur diameter for a focus shift `Δz`
(sensor off the focal plane) on an infinity object:
```
b = Δz / N      →     Δz = b · N
b = 2 px (6.9 µm)  →  Δz ≈ 9.7 µm
b = 3 px (10.4 µm) →  Δz ≈ 14.5 µm
```
So **~10–15 µm of focus travel** — a hair on the focus ring. (Same scale as the
diffraction depth of focus, `±2λN² ≈ ±2.2 µm`, and the thermal focus drift the
SoT flags: `Δz ≈ L·CTE·ΔT ≈ 0.40 µm/K`, i.e. 10 µm ≈ 25 K. The reason a small
defocus helps is the same reason thermal focus drift will bite — both live in
the few-µm regime.)

**Procedure:** focus to a crisp star, capture a set; then defocus until
`quicklook.py` reports brightest-star FWHM ≈ 2 px, capture another set. Keep the
focus-characterization exposures short (see trailing below) so motion blur does
not masquerade as defocus blur.

---

## Earth-rotation trailing (static tripod)

You are on a fixed tripod, so stars trail at the sidereal rate
`ω = 15.04 arcsec/s` (× cos(declination)):
```
trail_rate = ω · cos(dec) / plate_scale = 15.04 / 28.46 = 0.53 px/s  (at the celestial equator)
```
| exposure | trail @ equator |
|---|---|
| 0.1 s | 0.05 px |
| 0.2 s | 0.11 px |
| 0.5 s | 0.26 px |
| 1.0 s | 0.53 px |
| 2.0 s | 1.06 px |

So you have lots of exposure headroom. For **focus/PSF characterization** keep
exposure ≤ ~0.5 s so trailing stays well under the intended blur. For
**limiting-magnitude / SNR** frames you can push longer and just accept (or
later model) the trail.

> Note: on orbit the binding rate is the serving slew `ω = 0.821 deg/s`
> (SoT), which is ~196× the sidereal rate — i.e. ~0.43 px of smear in 4 ms.
> Joshua Tree characterizes focus, noise floor, limiting magnitude and the
> centroiding pipeline; it does **not** reproduce on-orbit smear. That is the
> `t_exp = smear_px · IFOV / ω` story, tested separately.

---

## Suggested capture sequence (≈ a few minutes total)

1. **Find the working point** — bracket sweep, lens capped *off*, focused:
   ```
   python3 capture.py --duration 60 \
     --bracket "20000:1,50000:2,100000:4,200000:8,500000:12,1000000:12" \
     --frames-per-setting 4 --focus-note "infinity sharp"
   ```
   Run `quicklook.py` on a few frames; pick the exp/gain with good star count
   and peak SNR without saturating bright stars.

2. **Focused science burst** at the chosen setting (~60 s):
   ```
   python3 capture.py --duration 60 --exposure-us <best> --gain <best> \
     --focus-note "infinity sharp"
   ```

3. **Defocused science burst** — back focus off to FWHM ≈ 2 px, repeat:
   ```
   python3 capture.py --duration 60 --exposure-us <best> --gain <best> \
     --focus-note "defocused, FWHM ~2 px"
   ```

4. **Darks** — same exposures/gains with the **lens cap on** (~20–30 s each
   setting). Gives bias + dark-current + fixed-pattern for noise/EMVA-style
   analysis and clean centroiding later:
   ```
   python3 capture.py --duration 30 --exposure-us <best> --gain <best> \
     --focus-note "DARK - lens cap ON" --preview-every 0
   ```

Label each run with `--focus-note` / `--note`; it lands in `session.json`.

---

## Headless auto-start on power (no screen)

Install the boot service once, at home on network:
```bash
cd ~/sauron-pi-capture
./field/install-service.sh
```
After that the Pi runs `capture.py` automatically ~20–40 s after it gets power
(systemd boot time — you cannot really beat that). No login, no screen needed.
Each power-on writes a new `data/session_YYYYmmdd_HHMMSS/`, so power-cycling
never overwrites data. Cutting power sends SIGTERM; the capture flushes its log
and exits cleanly (worst case you lose the single in-flight DNG).

**Change settings without a screen.** Capture settings live in
`startracker.conf` on the SD card's **boot partition**, which mounts on any
laptop (Windows/Mac). Pop the SD in a laptop, edit exposure/gain/mode, eject,
reboot the Pi. See `field/startracker.conf.example`.

**Two things that will bite you headless:**

1. **The clock.** The Pi 5 has an RTC but only keeps time across power-off if a
   **coin-cell battery is fitted to the RTC/BAT connector (J5)**. With no
   battery and no network (Joshua Tree), every boot the clock reloads the
   *fake-hwclock* time from last shutdown — so the absolute UTC stamp will be
   wrong. The per-frame `SensorTimestamp` (monotonic) is still perfectly good
   for *relative* timing within a session. Fixes, best to worst:
   - Fit the RTC battery and `sudo timedatectl` sync at home before leaving.
   - Or note the real wall-clock time (phone) at the moment you power the Pi,
     so you can re-peg `session.json`'s start time in post.
   - (Future) feed it GPS time.

2. **Focus.** You have no live preview in the field, so **set focus at home**:
   focus sharp on a distant target, then back off to the marked defocus point
   (see the defocus section) and record it in `FOCUS_NOTE`. Confirm later from
   the preview JPEGs / `quicklook.py`.

## Pre-departure checklist

- [ ] `rpicam-hello --list-cameras` shows `imx296`.
- [ ] **Sync the clock** on Wi-Fi before leaving (`timedatectl status` → NTP
      active). With no network at the site the UTC column is only as good as the
      Pi's RTC/last sync. Better: log GPS time, or note the offset.
- [ ] Confirm free space: `df -h` — full-res RAW is ~3 MB/frame.
- [ ] Test one short capture indoors; confirm DNG + CSV + a JPEG appear.
- [ ] Bring: lens cap (for darks), red headlamp, spare power (Pi 5 ≈ 5 V/5 A),
      something to keep the Pi warm (electronics + cold desert = condensation),
      and a stable tripod/mount.
- [ ] Record the **lens, focal length, f-number, and focus state** in
      `--lens` / `--focus-note`. Future-you will not remember.

## Disk budget

Full-res mono RAW ≈ `1456 × 1088 × 2 B ≈ 3.2 MB/frame`. At 0.2 s exposures
(~4–5 fps) a 60 s burst ≈ 1 GB. Plan SD card / exposures accordingly; capture
auto-stops at `--min-free-gb` (default 0.5 GB).
