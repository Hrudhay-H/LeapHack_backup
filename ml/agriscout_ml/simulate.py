"""Three-farm survey-day simulation built on REAL imagery with optional SIMULATED stress patches.

Real imagery: the healthy research-station site of the Thai UAV rice dataset (CC BY 4.0), stitched by
`mosaic_blb`. The site is split into four blocks:
  ref  - top-left block, used only to fit PatchCore's normal reference (never scored)
  a    - top-right block, left untouched            -> a real field with no injected stress
  b, c - bottom blocks, with simulated stress patches blended into the real bands

The injected patches are NOT real pest or disease damage. They shift the bands the way vegetation stress does
(red and red-edge up, NIR down, slight yellowing) with a soft edge, at known locations, so the pipeline's hits and
misses can be checked. Every survey carries this in survey.json and the UI/PDF repeat it.

  python -m agriscout_ml.simulate OUT_ROOT [--train MODEL.pt]
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import rasterio
from scipy import ndimage

from . import mosaic_blb

# block windows as (x0, y0, x1, y1) fractions of the healthy-site mosaic
BLOCKS = {
    "ref": (0.00, 0.00, 0.50, 0.50),
    "a": (0.50, 0.00, 1.00, 0.50),
    "b": (0.00, 0.50, 0.50, 1.00),
    "c": (0.50, 0.50, 1.00, 1.00),
}


@dataclass
class Stress:
    radius_m: float  # semi-axis along the patch's long direction
    severity: float  # 0..1, share of the full stress shift applied
    aspect: float = 1.0  # long axis / short axis
    angle_deg: float = 0.0
    name: str = ""


SCENARIOS: dict[str, list[Stress]] = {
    "a": [],
    "b": [
        Stress(2.0, 0.90, name="large severe patch"),
        Stress(1.3, 0.60, name="medium patch"),
        Stress(0.8, 0.45, name="small mild patch"),
    ],
    "c": [
        Stress(2.2, 0.70, aspect=3.2, angle_deg=30, name="elongated strip"),
        Stress(1.6, 0.55, name="medium patch"),
        Stress(1.0, 0.80, name="small severe patch"),
        Stress(0.6, 0.50, name="tiny patch"),
    ],
}


def _place(crop: np.ndarray, gsd: float, specs: list[Stress], seed: int):
    """Pick patch centres inside the crop (plots), away from paths and from each other."""
    rng = np.random.default_rng(seed)
    dist = ndimage.distance_transform_edt(crop) * gsd
    out, taken = [], []
    for sp in specs:
        need = max(sp.radius_m / sp.aspect, 0.4) + 0.3  # keep the patch's short half-width inside the plot
        cand = np.argwhere(dist > need)
        rng.shuffle(cand)
        for y, x in cand:
            if all(np.hypot(y - ty, x - tx) * gsd > sp.radius_m + tr + 1.0 for ty, tx, tr in taken):
                out.append((int(y), int(x)))
                taken.append((y, x, sp.radius_m))
                break
        else:
            raise RuntimeError(f"no room for patch {sp.name!r}")
    return out


def inject_stress(bands: np.ndarray, crop: np.ndarray, gsd: float, specs: list[Stress], seed: int = 0):
    """bands: (5,H,W) float [B,G,R,RE,NIR]. Returns (modified copy, truth mask of the affected area)."""
    out = bands.copy()
    truth = np.zeros(crop.shape, bool)
    yy, xx = np.mgrid[0 : crop.shape[0], 0 : crop.shape[1]].astype(np.float32)
    for sp, (cy, cx) in zip(specs, _place(crop, gsd, specs, seed)):
        a = sp.radius_m / gsd
        b = a / sp.aspect
        t = np.deg2rad(sp.angle_deg)
        u = (xx - cx) * np.cos(t) + (yy - cy) * np.sin(t)
        v = -(xx - cx) * np.sin(t) + (yy - cy) * np.cos(t)
        r = np.sqrt((u / a) ** 2 + (v / b) ** 2)
        soft = np.clip((1.15 - r) / 0.3, 0, 1) * crop  # soft edge, never outside the crop
        s = soft * sp.severity
        out[0] *= 1 - 0.05 * s  # blue
        out[1] *= 1 - 0.10 * s  # green
        out[2] *= 1 + 0.45 * s  # red
        out[3] *= 1 + 0.12 * s  # red edge rises with chlorophyll loss (a drop would leave NDRE unchanged)
        out[4] *= 1 - 0.30 * s  # NIR falls with canopy thinning
        truth |= soft > 0.5
    return out, truth


def build(out_root: Path, factor: int = 4) -> dict:
    ds, lab, ok, transform, crs, gsd = mosaic_blb.build_site(1, factor)
    H, W = ok.shape
    ndvi = (ds[4] - ds[2]) / (ds[4] + ds[2] + 1e-6)
    plots = ndimage.binary_fill_holes(ndimage.binary_opening(ok & (ndimage.gaussian_filter(ndvi, 2) > 0.2), iterations=4))
    info = {}
    for key, (fx0, fy0, fx1, fy1) in BLOCKS.items():
        x0, x1, y0, y1 = int(fx0 * W), int(fx1 * W), int(fy0 * H), int(fy1 * H)
        sl = (slice(y0, y1), slice(x0, x1))
        bands = ds[(slice(None), *sl)]
        okk = ok[sl]
        truth = np.zeros(okk.shape, bool)
        specs = SCENARIOS.get(key, [])
        if specs:
            bands, truth = inject_stress(bands, plots[sl], gsd, specs, seed=ord(key))
        tr = transform * rasterio.Affine.translation(x0, y0)
        d = out_root / f"sim_{key}"
        meta = mosaic_blb.write_survey(
            np.where(okk, bands, 0), lab[sl], okk, tr, crs, gsd, d, None, f"healthy_site_block_{key}", "healthy_site"
        )
        sj = json.loads((d / "survey.json").read_text())
        sj["data_source"] = "real_imagery_simulated_stress" if specs else "blb_thai_uav"
        sj["simulated_stress"] = (
            "Simulated stress patches were blended into this real imagery (band shifts mimicking vegetation stress). "
            "They are not real pest or disease damage."
            if specs
            else None
        )
        sj["planted"] = [asdict(s) for s in specs]
        sj["reflectance_calibrated"] = False
        (d / "survey.json").write_text(json.dumps(sj, indent=2))
        # truth mask for the pipeline's self-check, on the same cropped grid as the written rasters
        if specs:
            with rasterio.open(d / "rgb.tif") as r:
                gh, gw = r.height, r.width
                t2 = r.transform
            ys, xs = np.nonzero(okk)
            ty0, tx0 = ys.min(), xs.min()
            tcrop = truth[ty0 : ty0 + gh, tx0 : tx0 + gw]
            with rasterio.open(d / "truth_mask.tif", "w", driver="GTiff", height=gh, width=gw, count=1, dtype="uint8",
                               crs=crs, transform=t2, compress="deflate") as dst:
                dst.write(tcrop.astype(np.uint8)[None])
        info[key] = {k: meta[k] for k in ("size_px", "area_m2")} | {"patches": len(specs)}
    return info


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out_root", type=Path)
    ap.add_argument("--train", type=Path, metavar="MODEL", help="also fit the PatchCore normal reference on the 'ref' block")
    a = ap.parse_args()
    print(json.dumps(build(a.out_root), indent=2))
    if a.train:
        from . import pipeline

        print(json.dumps(pipeline.train([a.out_root / "sim_ref"], a.train), indent=2))
