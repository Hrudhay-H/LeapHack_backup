"""End-to-end pipeline: survey rasters -> anomaly maps -> hotspots -> artifacts.

CLI:
  python -m agriscout_ml.pipeline train --reference DIR [DIR ...] --model data/models/patchcore.pt
  python -m agriscout_ml.pipeline run --survey DIR --model data/models/patchcore.pt --out data/runs/ID
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.transform import array_bounds
from scipy import ndimage

from . import render
from .hotspots import extract_hotspots, fuse
from .io import Survey, load_survey
from .patchcore import PatchCore
from .spectral import crop_mask, indices, rgb_crop_mask, rgb_index_anomaly, spectral_anomaly

MODEL_VERSION = "agriscout-anomaly-v0.2"
# Index-led fusion: on every real dataset tested the vegetation-index branch beat PatchCore, which was near chance.
FUSION_W_RGB = 0.3  # provisional; weight of the experimental visual branch
WARNING = "Hotspots indicate potential crop anomalies and require field verification. They are not a diagnosis."


def _prep(s: Survey):
    """Vegetation indices (None for RGB-only surveys) and the crop mask."""
    if s.ms is None:
        return None, rgb_crop_mask(s.rgb, s.field_mask)
    idx = indices(s.ms)
    return idx, crop_mask(idx, s.field_mask, gsd_m=s.gsd_m)


def train(reference_dirs: list[Path], model_path: Path) -> dict:
    """Fit the PatchCore memory bank on NORMAL surveys; calibrate on held-out normal data.

    >=2 reference surveys: fit on all but the last, calibrate on the last.
    1 survey: spatial split (top 65% fit, 5% gap, bottom 30% calibrate).
    """
    surveys = [load_survey(d) for d in reference_dirs]
    preps = [_prep(s) for s in surveys]
    pc = PatchCore()
    if len(surveys) >= 2:
        fit_rgb = [s.rgb for s in surveys[:-1]]
        fit_crop = [p[1] for p in preps[:-1]]
        cal_rgb, cal_crop = surveys[-1].rgb, preps[-1][1]
        split = "held_out_survey"
    else:
        s, (_, crop) = surveys[0], preps[0]
        h = crop.shape[0]
        top, bot = crop.copy(), crop.copy()
        top[int(h * 0.65) :] = False
        bot[: int(h * 0.70)] = False
        fit_rgb, fit_crop = [s.rgb], [top]
        cal_rgb, cal_crop = s.rgb, bot
        split = "spatial_split_single_survey"
    bank_size = pc.fit(fit_rgb, fit_crop)
    cal = pc.calibrate(cal_rgb, cal_crop)
    pc.save(model_path)
    info = {"bank_size": bank_size, "calibration": cal.__dict__, "split": split, "n_reference_surveys": len(surveys)}
    model_path.with_suffix(".json").write_text(json.dumps(info, indent=2))
    return info


def edge_free(field_mask: np.ndarray, gsd_m: float, width_m: float = 1.0) -> np.ndarray:
    """True where a pixel is farther than width_m from the field boundary.

    PatchCore sees black or empty surroundings at a mosaic edge and scores those patches as strongly
    abnormal (on real maize mosaics every top-1% PatchCore pixel was at the boundary). The image border
    itself is not treated as an edge: only boundaries inside the raster are.
    """
    padded = np.pad(field_mask, 1, mode="edge")
    dist = ndimage.distance_transform_edt(padded)[1:-1, 1:-1] * gsd_m
    return dist > width_m


def _write_tif(path: Path, arr: np.ndarray, s: Survey) -> None:
    with rasterio.open(
        path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
        dtype="float32", crs=s.crs, transform=s.transform, compress="deflate",
    ) as dst:
        dst.write(arr.astype(np.float32), 1)


def _synthetic_check(survey_dir: Path, s: Survey, hotspot_mask: np.ndarray) -> dict | None:
    tp = survey_dir / "truth_mask.tif"
    if not tp.exists():
        return None
    from .io import _to_grid
    from rasterio.enums import Resampling

    truth = _to_grid(tp, 1, s.shape, s.transform, rasterio.crs.CRS.from_string(s.crs), Resampling.nearest, np.uint8)[0] > 0
    inter = (truth & hotspot_mask).sum()
    union = (truth | hotspot_mask).sum()
    lab, n = ndimage.label(truth)
    per_patch = []
    for i in range(1, n + 1):
        comp = lab == i
        if comp.sum() < 20:
            continue
        cov = float((hotspot_mask & comp).sum() / comp.sum())
        per_patch.append({"area_sqm": round(float(comp.sum() * s.gsd_m**2), 2), "coverage": round(cov, 2), "detected": cov >= 0.3})
    return {
        "note": "Evaluated against deliberately simulated stress patches. This tests pipeline localisation, not real-world pest-detection accuracy.",
        "pixel_iou": round(float(inter / max(union, 1)), 3),
        "pixel_recall": round(float(inter / max(truth.sum(), 1)), 3),
        "pixel_precision": round(float(inter / max(hotspot_mask.sum(), 1)), 3),
        "patches": per_patch,
    }


def run(survey_dir: Path, model_path: Path | None, out_dir: Path, survey_id: str = "SURVEY", progress=None) -> dict:
    """Run the full analysis. `progress(stage)` is called as each stage starts (quality, index, visual, hotspots, render)."""
    step = progress or (lambda _stage: None)
    out_dir.mkdir(parents=True, exist_ok=True)
    step("quality")
    s = load_survey(survey_dir)
    idx, crop = _prep(s)
    h, w = s.shape

    step("index")
    rgb_only = idx is None
    spec = rgb_index_anomaly(s.rgb, crop) if rgb_only else spectral_anomaly(idx, crop)
    a_ms = spec["score"]

    step("visual")
    a_rgb, rgb_raw = None, None
    if model_path and Path(model_path).exists():
        pc = PatchCore.load(Path(model_path))
        a_rgb, rgb_raw = pc.unit_map(s.rgb, crop)
        a_rgb = np.where(edge_free(s.field_mask, s.gsd_m), a_rgb, 0.0).astype(np.float32)
    fused = fuse(a_rgb, a_ms, crop, w_rgb=FUSION_W_RGB)

    step("hotspots")
    quality_ok = s.quality["nodata_fraction"] < 0.1 and s.quality["saturated_fraction"] < 0.1
    if not rgb_only:
        quality_ok = quality_ok and s.quality["looks_like_reflectance"] and s.quality["reflectance_calibrated"]
    geo, hot_mask, hs = extract_hotspots(
        fused, a_rgb, a_ms, crop, s.field_mask, s.transform, s.crs, s.gsd_m, quality_ok,
        index_label="RGB_INDEX" if rgb_only else "MULTISPECTRAL",
    )

    step("render")
    # Artifacts
    render.save_rgb(s.rgb, out_dir / "rgb.png")
    if not rgb_only:
        render.save_index(idx["ndvi"], crop, out_dir / "ndvi.png", 0.3, 0.9)
        render.save_index(idx["ndre"], crop, out_dir / "ndre.png", 0.0, 0.5)
    render.save_heat(a_ms, out_dir / "spectral_anomaly.png")
    # Raw deviation from the field median, including values below the alert floor, so a real field with no
    # alerts still shows where it varies most. Not an alert layer.
    render.save_heat(np.clip(spec["z"] / 4.0, 0.0, 1.0).astype(np.float32), out_dir / "spectral_z.png")
    if a_rgb is not None:
        render.save_heat(a_rgb, out_dir / "rgb_anomaly.png")
        _write_tif(out_dir / "rgb_anomaly.tif", a_rgb, s)
    render.save_heat(fused, out_dir / "fused_anomaly.png")
    render.save_overlay(s.rgb, hot_mask, out_dir / "overlay.png")
    _write_tif(out_dir / "spectral_anomaly.tif", a_ms, s)
    _write_tif(out_dir / "fused_anomaly.tif", fused, s)
    (out_dir / "hotspots.geojson").write_text(json.dumps(geo))

    west, south, east, north = array_bounds(h, w, s.transform)
    to_wgs = Transformer.from_crs(s.crs, "EPSG:4326", always_xy=True).transform
    (lw, ls), (le, ln) = to_wgs(west, south), to_wgs(east, north)

    summary = {
        "survey_id": survey_id,
        "model_version": MODEL_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data_source": s.meta.get("data_source", "real"),
        "input_modalities": (["RGB"] if rgb_only or a_rgb is not None else []) + ([] if rgb_only else ["MULTISPECTRAL"]),
        "analysis_branches": (["VARI (RGB colour index)"] if rgb_only else ["NDVI/NDRE (multispectral)"])
        + (["PatchCore (visual texture, experimental)"] if a_rgb is not None else []),
        "image": {"width_px": w, "height_px": h, "gsd_m": s.gsd_m, "bounds_wgs84": [ls, lw, ln, le]},
        "quality": {**s.quality, "quality_ok": quality_ok},
        "summary": hs,
        "branches": {
            "spectral": {"max_unit": float(a_ms.max()), "area_flagged_pct": round(100 * float((a_ms > 0.2).sum() / max(crop.sum(), 1)), 2)},
            "rgb_patchcore": None if a_rgb is None else {"max_unit": float(a_rgb.max()), "area_flagged_pct": round(100 * float((a_rgb > 0.2).sum() / max(crop.sum(), 1)), 2)},
        },
        "parameters": {"hotspot_threshold": 0.25, "min_area_m2": 1.0, "fusion_weights": {"rgb": FUSION_W_RGB, "spectral": round(1 - FUSION_W_RGB, 2)}, "spectral_z_floor": 2.5},
        "warning": WARNING,
        "dataset": {k: s.meta[k] for k in ("crop", "source", "doi", "license", "attribution", "site", "simulated_stress") if s.meta.get(k)} or None,
    }
    check = _synthetic_check(Path(survey_dir), s, hot_mask)
    if check:
        summary["synthetic_check"] = check
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--reference", nargs="+", type=Path, required=True)
    t.add_argument("--model", type=Path, required=True)
    r = sub.add_parser("run")
    r.add_argument("--survey", type=Path, required=True)
    r.add_argument("--model", type=Path)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--survey-id", default="SURVEY")
    a = ap.parse_args()
    if a.cmd == "train":
        print(json.dumps(train(a.reference, a.model), indent=2))
    else:
        print(json.dumps(run(a.survey, a.model, a.out, a.survey_id)["summary"], indent=2))


if __name__ == "__main__":
    main()
