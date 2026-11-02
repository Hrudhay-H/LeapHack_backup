"""Vegetation indices, crop mask and the robust field-relative spectral baseline."""
from __future__ import annotations

import numpy as np
from scipy import ndimage

EPS = 1e-6


def nd(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return (a - b) / (a + b + EPS)


def indices(ms: np.ndarray) -> dict[str, np.ndarray]:
    red, green, rededge, nir = ms
    return {"ndvi": nd(nir, red), "ndre": nd(nir, rededge), "gndvi": nd(nir, green)}


def otsu_threshold(values: np.ndarray, bins: int = 128) -> float:
    hist, edges = np.histogram(values, bins=bins)
    p = hist.astype(np.float64) / max(hist.sum(), 1)
    centres = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(p)
    mu = np.cumsum(p * centres)
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mu[-1] * w0 - mu) ** 2 / (w0 * (1 - w0))
    return float(centres[int(np.nanargmax(between))])


def crop_mask(
    idx: dict[str, np.ndarray],
    field_mask: np.ndarray,
    ndvi_min: float | None = None,
    gsd_m: float | None = None,
    max_hole_m2: float = 20.0,
) -> np.ndarray:
    """Vegetated pixels inside the field boundary; excludes bunds, paths, water, bare soil.

    ndvi_min=None picks the vegetation/background split from the survey itself (Otsu on NDVI inside the field,
    bounded to 0.20..0.40) because absolute NDVI differs between sensors and exposures. Enclosed gaps smaller than
    max_hole_m2 are filled back in, so a badly stressed patch inside a crop block (very low NDVI) is not dropped
    as 'not crop'; stressed patches touching a path or the boundary cannot be told apart from bare ground.
    """
    ndvi = idx["ndvi"]
    if ndvi_min is None:
        vals = ndvi[field_mask & np.isfinite(ndvi)]
        ndvi_min = float(np.clip(otsu_threshold(vals), 0.20, 0.40)) if vals.size > 1000 else 0.35
    m = (ndvi > ndvi_min) & field_mask
    m = ndimage.binary_opening(m, iterations=2)
    m = ndimage.binary_closing(m, iterations=2)
    if gsd_m:
        holes = ndimage.binary_fill_holes(m) & ~m
        lab, n = ndimage.label(holes)
        if n:
            sizes = ndimage.sum(holes, lab, range(1, n + 1)) * gsd_m**2
            small = np.isin(lab, [i + 1 for i, a in enumerate(sizes) if a <= max_hole_m2])
            m = m | small
    return m & field_mask


def robust_z(x: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Median/MAD z-score over valid pixels only. Negative = below field median."""
    vals = x[valid]
    med = np.median(vals)
    mad = np.median(np.abs(vals - med))
    return (x - med) / (1.4826 * mad + EPS)


def spectral_anomaly(
    idx: dict[str, np.ndarray],
    crop: np.ndarray,
    smooth_sigma_px: float = 3.0,
    z_floor: float = 2.5,
    z_full: float = 7.0,
) -> dict[str, np.ndarray]:
    """Field-relative low-vigour anomaly from NDVI and NDRE.

    Returns the raw z (positive = unusually low vigour), and a 0..1 score that is
    exactly 0 below z_floor, so a healthy field yields no anomaly rather than a
    forced top-percentile. z_floor/z_full are provisional and need calibration.
    """
    zs = []
    for name in ("ndre", "ndvi"):
        x = idx[name].copy()
        # Normalised convolution so masked-out pixels do not leak into the smooth.
        w = crop.astype(np.float32)
        num = ndimage.gaussian_filter(np.where(crop, x, 0).astype(np.float32), smooth_sigma_px)
        den = ndimage.gaussian_filter(w, smooth_sigma_px) + EPS
        xs = np.where(crop, num / den, np.nan)
        z = robust_z(np.nan_to_num(xs, nan=np.nanmedian(xs)), crop)
        zs.append(-z)  # low index = anomalous
    z_low = np.mean(zs, axis=0)
    z_low = np.where(crop, z_low, 0.0)
    score = np.clip((z_low - z_floor) / (z_full - z_floor), 0.0, 1.0)
    return {"z": z_low.astype(np.float32), "score": score.astype(np.float32)}


def rgb_crop_mask(rgb: np.ndarray, field_mask: np.ndarray, exg_min: float = 0.15) -> np.ndarray:
    """Crop mask for RGB-only surveys (no NIR to separate vegetation from soil).

    Canopy = excess-green above exg_min; enclosed gaps (stressed or thinned patches surrounded by canopy)
    are filled back in. A stressed patch that touches a bund or the field edge cannot be told apart from
    bare ground without NIR and stays excluded, so the field boundary should exclude bunds where known.
    """
    r, g, b = rgb.astype(np.float32) / 255.0
    exg = (2 * g - r - b) / (r + g + b + EPS)
    canopy = ndimage.binary_opening((exg > exg_min) & field_mask, iterations=2)
    filled = ndimage.binary_fill_holes(canopy) & field_mask
    return ndimage.binary_closing(filled, iterations=2) & field_mask


def rgb_index_anomaly(
    rgb: np.ndarray,
    crop: np.ndarray,
    smooth_sigma_px: float = 3.0,
    z_floor: float = 2.5,
    z_full: float = 7.0,
) -> dict[str, np.ndarray]:
    """Field-relative low-greenness anomaly from VARI = (G-R)/(G+R-B), for RGB-only drones.

    Same robust median/MAD scoring and absolute floor as the multispectral baseline. VARI saturates and is
    sensitive to illumination, so it is a weaker proxy for vigour than NDRE.
    """
    r, g, b = rgb.astype(np.float32) / 255.0
    v = np.clip((g - r) / (g + r - b + 1e-3), -1.0, 1.0)
    w = crop.astype(np.float32)
    num = ndimage.gaussian_filter(np.where(crop, v, 0).astype(np.float32), smooth_sigma_px)
    den = ndimage.gaussian_filter(w, smooth_sigma_px) + EPS
    vs = np.where(crop, num / den, np.nan)
    z = -robust_z(np.nan_to_num(vs, nan=np.nanmedian(vs)), crop)
    z = np.where(crop, z, 0.0)
    score = np.clip((z - z_floor) / (z_full - z_floor), 0.0, 1.0)
    return {"z": z.astype(np.float32), "score": score.astype(np.float32)}
