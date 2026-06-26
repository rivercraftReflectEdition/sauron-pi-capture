#!/usr/bin/env python3
"""
quicklook.py -- eyeball a captured DNG and sanity-check the star data.

Reads a RAW DNG, applies a percentile + asinh stretch (so faint stars pop
without blowing out bright ones), writes a PNG, and prints a few numbers that
tell you whether the exposure/focus was any good:

  * background level and noise (median + MAD of the dim pixels)
  * how many connected bright blobs (rough star count) cross a threshold
  * the brightest blob's FWHM in pixels -- this is the number that tells you
    whether you are well-sampled for sub-pixel centroiding (target ~1.5-2.5 px).

This is a *field sanity tool*, not the real centroiding pipeline.

Deps (fine to pip install, separate from picamera2):
    pip install rawpy numpy pillow scipy

Usage:
    python3 quicklook.py data/session_XXXX/raw/000010.dng
    python3 quicklook.py data/session_XXXX/raw/000010.dng --thresh-sigma 6
"""

import argparse
import os
import sys

import numpy as np


def load_raw(path):
    import rawpy
    with rawpy.imread(path) as raw:
        img = raw.raw_image_visible.astype(np.float64)
    return img


def fwhm_of_brightest(img, bg, sigma, thresh):
    """Crude FWHM (px) of the brightest blob, via 2nd moments above half-max."""
    try:
        from scipy import ndimage
    except ImportError:
        return None
    mask = img > thresh
    if not mask.any():
        return None
    labels, n = ndimage.label(mask)
    if n == 0:
        return None
    sums = ndimage.sum(img - bg, labels, index=range(1, n + 1))
    brightest = int(np.argmax(sums)) + 1
    ys, xs = np.where(labels == brightest)
    w = (img - bg)[ys, xs]
    w = np.clip(w, 0, None)
    if w.sum() <= 0:
        return None
    cx = (xs * w).sum() / w.sum()
    cy = (ys * w).sum() / w.sum()
    varx = (w * (xs - cx) ** 2).sum() / w.sum()
    vary = (w * (ys - cy) ** 2).sum() / w.sum()
    sigma_px = np.sqrt((varx + vary) / 2.0)
    return 2.3548 * sigma_px  # Gaussian FWHM = 2.355 * sigma


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dng")
    ap.add_argument("--out", default="", help="output PNG (default: alongside)")
    ap.add_argument("--thresh-sigma", type=float, default=5.0,
                    help="star detection threshold above background, in sigma")
    args = ap.parse_args()

    try:
        img = load_raw(args.dng)
    except ImportError:
        sys.exit("Need rawpy: pip install rawpy numpy pillow scipy")

    # Robust background stats from the lower half of the histogram.
    bg = np.median(img)
    mad = np.median(np.abs(img - bg))
    sigma = 1.4826 * mad if mad > 0 else (img.std() or 1.0)
    thresh = bg + args.thresh_sigma * sigma

    # Rough star count via connected components.
    n_blobs = None
    try:
        from scipy import ndimage
        _, n_blobs = ndimage.label(img > thresh)
    except ImportError:
        pass

    fwhm = fwhm_of_brightest(img, bg, sigma, thresh)

    print(f"file               : {args.dng}")
    print(f"shape              : {img.shape}  dtype-range: "
          f"{img.min():.0f}..{img.max():.0f}")
    print(f"background (median): {bg:.1f}")
    print(f"noise sigma (MAD)  : {sigma:.2f}")
    print(f"detect threshold   : {thresh:.1f}  ({args.thresh_sigma} sigma)")
    print(f"peak SNR (brightest): {(img.max() - bg) / sigma:.1f}")
    if n_blobs is not None:
        print(f"blobs above thresh : {n_blobs}  (rough star count)")
    if fwhm is not None:
        print(f"brightest FWHM     : {fwhm:.2f} px  "
              f"(centroiding sweet spot ~1.5-2.5 px)")
        if fwhm < 1.0:
            print("  -> UNDER-SAMPLED: star is basically a point. Defocus a hair.")
        elif fwhm > 4.0:
            print("  -> Over-blurred: SNR/limiting-mag suffers. Tighten focus.")
        else:
            print("  -> Good sampling for sub-pixel centroiding.")

    # Stretch + save PNG.
    try:
        from PIL import Image
    except ImportError:
        print("\n(install pillow to also write a PNG: pip install pillow)")
        return
    lo = bg
    hi = np.percentile(img, 99.95)
    scale = 5.0  # asinh softening
    stretched = np.arcsinh(np.clip((img - lo) / max(hi - lo, 1) * scale, 0, None))
    stretched = stretched / stretched.max() if stretched.max() > 0 else stretched
    out8 = (np.clip(stretched, 0, 1) * 255).astype(np.uint8)
    out_path = args.out or os.path.splitext(args.dng)[0] + "_quicklook.png"
    Image.fromarray(out8).save(out_path)
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
