#!/usr/bin/env python3
"""
exposure_model.py -- where the capture bracket comes from.

Reproduces the f/1.4 exposure vs limiting-magnitude / saturation / trailing
table using the same photon-model family as the optical theory notebook
(outputs/Notebooks/SauronTheory.ipynb). Run it to re-derive the bracket if any
input (focal length, f-number, sensor, slew) changes.

    python3 analysis/exposure_model.py

No dependencies beyond the standard library.
"""

import math

# --- constants for the IMX296 field-capture bracket ------------------------ #
PHI0 = 3.6e10        # photons / m^2 / s for a mag-0 V-like star
F_MM = 25.0
N = 1.4
THRU = 0.85          # OPTICS_THROUGHPUT
QE = 0.6429          # IMX296 (FLIR EMVA proxy)
RN = 4.81            # e- read noise
FULLWELL = 10636     # e-
NPIX = 9             # CENTROID_WINDOW_PIXELS
SNRDET = 5.0
PIX_UM = 3.45
OMEGA_ORBIT = 0.821  # deg/s serving slew (the on-orbit binding rate)

# Joshua Tree sky brightness for the background sanity check.
SKY_MAG_ARCSEC2 = 21.5

ARCSEC_RAD = 206264.806


def main():
    D_m = (F_MM / N) * 1e-3
    A = math.pi * (D_m / 2) ** 2                 # aperture area, m^2
    R0 = PHI0 * A * QE * THRU                     # e-/s from a mag-0 star
    ifov_rad = (PIX_UM * 1e-3) / F_MM
    ifov_as = ifov_rad * ARCSEC_RAD

    # limiting signal for SNR=5 over NPIX with read noise (quadratic solve)
    q = SNRDET ** 2
    slim = (q + math.sqrt(q ** 2 + 4 * q * NPIX * RN ** 2)) / 2

    # on-orbit smear-limited exposure (1 px streak)
    t_orbit = 1.0 * ifov_rad / math.radians(OMEGA_ORBIT)

    # ground trailing at the sidereal rate
    sidereal_as_s = 360 / 86164 * 3600            # arcsec/s
    trail_px_s = sidereal_as_s / ifov_as

    # sky background per pixel
    px_solid_arcsec2 = ifov_as ** 2
    sky_mag_px = SKY_MAG_ARCSEC2 - 2.5 * math.log10(px_solid_arcsec2)
    sky_e_s_px = R0 * 10 ** (-0.4 * sky_mag_px)

    def vlim(t):
        return -2.5 * math.log10(slim / (R0 * t))

    def stot(m, t):
        return R0 * 10 ** (-0.4 * m) * t

    print(f"aperture D = {F_MM/N:.2f} mm,  area = {A*1e6:.1f} mm^2")
    print(f"plate scale = {ifov_as:.2f} arcsec/px")
    print(f"R0 (mag-0)  = {R0:.3e} e-/s")
    print(f"S_lim (SNR{SNRDET:g}, {NPIX}px, RN{RN}) = {slim:.1f} e-")
    print(f"V_lim(t) = {-2.5*math.log10(slim/R0):.2f} + 2.5*log10(t[s])")
    print()
    print(f"on-orbit smear exposure (1px @ {OMEGA_ORBIT} deg/s) = "
          f"{t_orbit*1e3:.2f} ms -> V_lim {vlim(t_orbit):.2f}")
    print(f"ground trailing = {trail_px_s:.3f} px/s "
          f"(orbit/sidereal rate ratio = {OMEGA_ORBIT/(sidereal_as_s/3600):.0f}x)")
    print(f"1px-trail ground exposure limit = {1/trail_px_s*1e3:.0f} ms")
    print(f"sky bg ~ {sky_e_s_px:.1f} e-/s/px (sky shot-noise crosses read "
          f"noise near {RN**2/sky_e_s_px:.1f} s)")
    print()
    hdr = f"{'t_exp':>8} {'V_lim':>6} {'trail_px':>9} {'m2_etot':>9} {'m4_etot':>9} {'m6_etot':>9}"
    print(hdr)
    print("-" * len(hdr))
    for t_ms in [5, 10, 20, 50, 100, 200, 500, 1000, 2000]:
        t = t_ms / 1e3
        print(f"{t_ms:>6}ms {vlim(t):>6.2f} {trail_px_s*t:>9.3f} "
              f"{stot(2,t):>9.0f} {stot(4,t):>9.0f} {stot(6,t):>9.0f}")
    print(f"\n(full well = {FULLWELL} e-; total exceeding it = saturated guide star)")


if __name__ == "__main__":
    main()
