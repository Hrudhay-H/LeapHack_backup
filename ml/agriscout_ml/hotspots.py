"""Fusion of anomaly maps and extraction of actionable hotspot polygons."""
from __future__ import annotations

import numpy as np
from pyproj import Transformer
from rasterio.features import shapes
from scipy import ndimage
from shapely.geometry import mapping, shape
from shapely.ops import transform as shp_transform, unary_union
from skimage.measure import label, regionprops

AGREE_T = 0.2  # a branch "fires" above this unit score


def fuse(a_rgb: np.ndarray | None, a_ms: np.ndarray | None, crop: np.ndarray, w_rgb: float = 0.5) -> np.ndarray:
    """Equal-weight score fusion with single-modality fallback.

    Not a probability: a combined anomaly signal. Weights are provisional.
    """
    if a_rgb is None and a_ms is None:
        raise ValueError("need at least one anomaly branch")
    if a_rgb is None:
        out = a_ms
    elif a_ms is None:
        out = a_rgb
    else:
        out = w_rgb * a_rgb + (1 - w_rgb) * a_ms
    return np.where(crop, out, 0.0).astype(np.float32)


def _pattern_hint(comp: np.ndarray, crop: np.ndarray, field_px: np.ndarray, crop_area_px: int):
    props = regionprops(comp.astype(np.uint8))[0]
    area = props.area
    minor = max(props.axis_minor_length, 1.0)
    elong = props.axis_major_length / minor
    ring = ndimage.binary_dilation(comp, iterations=8) & ~comp
    ring_total = max(int(ring.sum()), 1)
    edge_frac = float((ring & field_px & ~crop).sum() / ring_total)
    # Touching the image/field edge also counts as boundary-aligned.
    ys, xs = np.nonzero(comp)
    h, w = comp.shape
    on_border = ys.min() <= 2 or xs.min() <= 2 or ys.max() >= h - 3 or xs.max() >= w - 3
    frac = area / max(crop_area_px, 1)

    if edge_frac > 0.35 or on_border:
        return (
            "edge_aligned",
            "Pattern aligned with a field edge or bund: possible boundary, drainage or shading effect. Inspect on the ground.",
        )
    if frac > 0.15:
        return (
            "broad_gradient",
            "Broad region: possible water, nutrient or crop-stage variation. Check irrigation and fertiliser records first.",
        )
    if elong > 3.0:
        return (
            "elongated",
            "Elongated region: possible directional water or nutrient variation. Inspect along its length.",
        )
    return (
        "compact_patch",
        "Pattern consistent with localised stress. Inspect for pest damage and other causes.",
    )


def _confidence(quality_ok: bool, agreement: float, area_m2: float) -> str:
    if not quality_ok or area_m2 < 1.5 or agreement < 0.15:
        return "LOW"
    if agreement >= 0.5 and area_m2 >= 3.0:
        return "HIGH"
    return "MEDIUM"


def _priority(frac_of_crop: float, mean_score: float) -> str:
    if frac_of_crop >= 0.08 and mean_score >= 0.4:
        return "CRITICAL"
    if frac_of_crop >= 0.02 or mean_score >= 0.6:
        return "HIGH"
    if frac_of_crop >= 0.008 or mean_score >= 0.35:
        return "MODERATE"
    return "LOW"


def extract_hotspots(
    fused: np.ndarray,
    a_rgb: np.ndarray | None,
    a_ms: np.ndarray | None,
    crop: np.ndarray,
    field_px: np.ndarray,
    transform,
    crs: str,
    gsd_m: float,
    quality_ok: bool,
    index_label: str = "MULTISPECTRAL",
    threshold: float = 0.25,
    min_area_m2: float = 1.0,
):
    """Threshold -> clean -> components -> polygons with metadata.

    Returns (geojson FeatureCollection dict, boolean hotspot mask, summary dict).
    """
    mask = (fused >= threshold) & crop
    mask = ndimage.binary_opening(mask, iterations=1)
    mask = ndimage.binary_closing(mask, iterations=2) & crop
    lab = label(mask, connectivity=2)
    px_area = gsd_m**2
    min_px = max(int(min_area_m2 / px_area), 1)
    crop_area_px = int(crop.sum())

    to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
    feats, kept = [], np.zeros(lab.shape, dtype=bool)
    for cid in range(1, lab.max() + 1):
        comp = lab == cid
        n_px = int(comp.sum())
        if n_px < min_px:
            continue
        geoms = [shape(g) for g, v in shapes(comp.astype(np.uint8), mask=comp, transform=transform) if v == 1]
        poly = unary_union(geoms).simplify(gsd_m, preserve_topology=True)
        area_m2 = float(poly.area)  # projected (metric) CRS
        mean_score = float(fused[comp].mean())
        agree = float(((a_rgb[comp] > AGREE_T) & (a_ms[comp] > AGREE_T)).mean()) if a_rgb is not None and a_ms is not None else 0.0
        r_mean = float(a_rgb[comp].mean()) if a_rgb is not None else 0.0
        m_mean = float(a_ms[comp].mean()) if a_ms is not None else 0.0
        if agree >= 0.5:
            dominant = "BOTH"
        else:
            dominant = "RGB" if r_mean > m_mean else index_label
        pattern, hint = _pattern_hint(comp, crop, field_px, crop_area_px)
        frac = n_px / max(crop_area_px, 1)
        cx, cy = poly.centroid.x, poly.centroid.y
        lon, lat = to_wgs(cx, cy)
        kept[comp] = True
        feats.append(
            {
                "type": "Feature",
                "geometry": mapping(shp_transform(to_wgs, poly)),
                "properties": {
                    "anomaly_score": round(mean_score, 3),
                    "peak_score": round(float(fused[comp].max()), 3),
                    "estimated_area_sqm": round(area_m2, 1),
                    "crop_area_percent": round(100 * frac, 2),
                    "priority": _priority(frac, mean_score),
                    "confidence": _confidence(quality_ok, agree, area_m2),
                    "agreement": round(agree, 2),
                    "dominant_signal": dominant,
                    "rgb_signal": round(r_mean, 3),
                    "spectral_signal": round(m_mean, 3),
                    "pattern": pattern,
                    "pattern_hint": hint,
                    "centroid": [round(lon, 6), round(lat, 6)],
                    "ground_verification_status": "PENDING",
                },
            }
        )

    order = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2, "LOW": 3}
    feats.sort(key=lambda f: (order[f["properties"]["priority"]], -f["properties"]["estimated_area_sqm"]))
    for i, f in enumerate(feats, 1):
        f["properties"]["hotspot_id"] = f"HS_{i:03d}"
        f["id"] = f["properties"]["hotspot_id"]

    sus_px = int(kept.sum())
    summary = {
        "valid_crop_area_sqm": round(crop_area_px * px_area, 1),
        "suspicious_area_sqm": round(sus_px * px_area, 1),
        "suspicious_area_percent": round(100 * sus_px / max(crop_area_px, 1), 2),
        "hotspots_detected": len(feats),
        "status": "anomalies_detected" if feats else "no_significant_anomaly",
    }
    return {"type": "FeatureCollection", "features": feats}, kept, summary
