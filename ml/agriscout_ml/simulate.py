"""Survey simulation on REAL imagery: a real rice research-station mosaic with SIMULATED stress patches blended in.

Real imagery: the healthy site of the Thai UAV rice dataset (CC BY 4.0), stitched by `mosaic_blb`. It is cut into four
blocks:
  ref  - used only to fit the visual check's normal reference (never scored)
  a, b, c - one block per demo farm

The stress is NOT real pest or disease damage. It is drawn to look like field damage so the demo is believable, and it is
recorded in every survey's metadata and repeated in the UI and PDF:
  * irregular, noise-warped outlines rather than ellipses
  * severity that varies inside a patch and fades toward the edge
  * thinning: speckled gaps where real bare ground from the same image shows through
  * optional satellite foci around a main patch (how a spreading infestation often looks)
  * stress is confined to the crop plots and fades at plot edges
Patches have two states so a farm can have history: `earlier` (small or mild) and `now` (grown, with satellites).

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
class Patch:
    name: str
    radius_m: float  # long semi-axis at the later survey
    severity: float  # 0..1 peak severity at the later survey
    aspect: float = 1.0  # long axis / short axis
    angle_deg: float = 0.0
    earlier: tuple[float, float] | None = None  # (size fraction, severity fraction) at the earlier survey; None = not there yet
    satellites: int = 0  # small foci around the patch at the later survey only


# What each farm looks like, by block. An empty list is a real, untouched field.
SCENARIOS: dict[str, list[Patch]] = {
    "a": [],
    "b": [
        Patch("main patch", 3.2, 0.82, aspect=1.2, angle_deg=20, earlier=(0.78, 0.92), satellites=3),
        Patch("new patch", 1.2, 0.65),
    ],
    "c": [
        Patch("edge strip", 2.4, 0.70, aspect=3.0, angle_deg=25),
        Patch("mid-field patch", 1.5, 0.60, aspect=1.1, angle_deg=70),
    ],
}


def _grid_noise(seed: int, n: int, sigma: float) -> np.ndarray:
    g = ndimage.gaussian_filter(np.random.default_rng(seed).normal(size=(n, n)), sigma, mode="wrap")
    return g / (np.abs(g).max() + 1e-9)


def _sample(grid: np.ndarray, u: np.ndarray, v: np.ndarray, extent: float = 3.0) -> np.ndarray:
    """Sample a fixed noise grid in patch-normalised coordinates, so a patch keeps its character as it grows."""
    n = grid.shape[0]
    cu = (u + extent) / (2 * extent) * (n - 1)
    cv = (v + extent) / (2 * extent) * (n - 1)
    return ndimage.map_coordinates(grid, [cv, cu], order=3, mode="nearest")


def _smooth(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def _severity(shape, cx, cy, gsd, radius_m, aspect, angle_deg, peak, seed) -> np.ndarray:
    """One irregular, patchy stress patch as a 0..1 severity map."""
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]].astype(np.float32)
    a = max(radius_m / gsd, 1.0)
    b = a / aspect
    t = np.deg2rad(angle_deg)
    u = ((xx - cx) * np.cos(t) + (yy - cy) * np.sin(t)) / a
    v = (-(xx - cx) * np.sin(t) + (yy - cy) * np.cos(t)) / b
    r = np.sqrt(u**2 + v**2)
    outline = _sample(_grid_noise(seed, 14, 1.6), u, v)  # warps the boundary
    detail = _sample(_grid_noise(seed + 1, 30, 1.8), u, v)  # variation inside
    rw = r * (1.0 + 0.38 * outline)
    core = _smooth((1.05 - rw) / 0.55)
    return peak * core * (0.80 + 0.20 * detail)


def _patch_state(shape, c, gsd, p: Patch, state: str, seed: int) -> np.ndarray:
    if state == "earlier":
        if p.earlier is None:
            return np.zeros(shape, np.float32)
        size, sev = p.earlier
    else:
        size, sev = 1.0, 1.0
    out = _severity(shape, c[1], c[0], gsd, p.radius_m * size, p.aspect, p.angle_deg, p.severity * sev, seed)
    if state == "now" and p.satellites:
        rng = np.random.default_rng(seed + 7)
        t = np.deg2rad(p.angle_deg)
        for k in range(p.satellites):
            ang = rng.uniform(0, 2 * np.pi)
            dist = p.radius_m * rng.uniform(1.55, 1.95)
            dx, dy = np.cos(ang) * dist / gsd, np.sin(ang) * dist / gsd
            out = np.maximum(
                out,
                _severity(shape, c[1] + dx, c[0] + dy, gsd, p.radius_m * rng.uniform(0.22, 0.34), 1.0, 0, 0.6 * p.severity, seed + 11 + k),
            )
    return out.astype(np.float32)


def _place(plots: np.ndarray, gsd: float, patches: list[Patch], seed: int):
    """Choose patch centres well inside the crop plots and apart from each other."""
    rng = np.random.default_rng(seed)
    dist = ndimage.distance_transform_edt(plots) * gsd
    out, taken = [], []
    for p in patches:
        need = max(p.radius_m / p.aspect, 0.5) * 0.9
        cand = np.argwhere(dist > need)
        rng.shuffle(cand)
        for y, x in cand:
            if all(np.hypot(y - ty, x - tx) * gsd > (p.radius_m + tr) * 1.5 + 1.0 for ty, tx, tr in taken):
                out.append((int(y), int(x)))
                taken.append((y, x, p.radius_m))
                break
        else:
            raise RuntimeError(f"no room for patch {p.name!r}")
    return out


def inject_stress(bands: np.ndarray, plots: np.ndarray, gsd: float, patches: list[Patch], state: str = "now", seed: int = 0):
    """bands: (5,H,W) float [B,G,R,RE,NIR]. Returns (modified copy, truth mask of visibly stressed pixels)."""
    shape = plots.shape
    centres = _place(plots, gsd, patches, seed)
    sev = np.zeros(shape, np.float32)
    for i, (p, c) in enumerate(zip(patches, centres)):
        sev = np.maximum(sev, _patch_state(shape, c, gsd, p, state, seed * 100 + 13 * i + 5))
    sev *= ndimage.gaussian_filter(plots.astype(np.float32), 1.8)  # fades at plot edges, never spills onto paths
    out = bands.copy()
    if sev.max() <= 0:
        return out, np.zeros(shape, bool)
    # Thinning: speckled gaps showing real bare ground from the same image (paths between plots).
    path = bands[:, ~plots & (bands.sum(axis=0) > 0)]
    soil = np.median(path, axis=1) if path.shape[1] > 200 else bands.mean(axis=(1, 2))
    h = ndimage.gaussian_filter(np.random.default_rng(seed + 99).normal(size=shape), 1.1)
    h /= h.std() + 1e-9
    gap = np.clip((sev - 0.30) / 0.45, 0, 1) * _smooth((h - 0.1) / 1.0) * 0.55
    out = out * (1 - gap) + soil[:, None, None] * gap
    # A visibly damaged canopy: chlorophyll loss lifts red and red-edge reflectance, thinning drops NIR, and the leaf
    # yellows/browns (blue and green fall less than red rises). Strength is chosen so the damage is plainly visible in RGB.
    out[0] *= 1 - 0.10 * sev  # blue
    out[1] *= 1 - 0.04 * sev  # green
    out[2] *= 1 + 1.00 * sev  # red
    out[3] *= 1 + 0.22 * sev  # red edge rises with chlorophyll loss (a drop would leave NDRE unchanged)
    out[4] *= 1 - 0.38 * sev  # NIR falls with canopy thinning
    return out, sev > 0.20


def _write(d: Path, ds, lab, okk, tr, crs, gsd, name: str, planted: list[dict], truth: np.ndarray | None, stressed: bool):
    meta = mosaic_blb.write_survey(np.where(okk, ds, 0), lab, okk, tr, crs, gsd, d, None, name, "healthy_site")
    sj = json.loads((d / "survey.json").read_text())
    sj["data_source"] = "real_imagery_simulated_stress" if stressed else "blb_thai_uav"
    sj["simulated_stress"] = (
        "Simulated stress patches were blended into this real imagery (band shifts, thinning and irregular outlines "
        "mimicking crop damage). They are not real pest or disease damage."
        if stressed
        else None
    )
    sj["planted"] = planted
    sj["reflectance_calibrated"] = False
    (d / "survey.json").write_text(json.dumps(sj, indent=2))
    if truth is not None and truth.any():
        with rasterio.open(d / "rgb.tif") as r:
            gh, gw, t2 = r.height, r.width, r.transform
        ys, xs = np.nonzero(okk)
        crop = truth[ys.min() : ys.min() + gh, xs.min() : xs.min() + gw]
        with rasterio.open(d / "truth_mask.tif", "w", driver="GTiff", height=gh, width=gw, count=1, dtype="uint8", crs=crs, transform=t2, compress="deflate") as dst:
            dst.write(crop.astype(np.uint8)[None])
    return {k: meta[k] for k in ("size_px", "area_m2")}


def build(out_root: Path, factor: int = 4) -> dict:
    """Write sim_ref, and for each farm block the latest survey `sim_<k>` plus, where a farm has history, `sim_<k>_prev`."""
    ds, lab, ok, transform, crs, gsd = mosaic_blb.build_site(1, factor)
    H, W = ok.shape
    ndvi = (ds[4] - ds[2]) / (ds[4] + ds[2] + 1e-6)
    plots = ndimage.binary_fill_holes(ndimage.binary_opening(ok & (ndimage.gaussian_filter(ndvi, 2) > 0.2), iterations=4))
    info = {}
    for key, (fx0, fy0, fx1, fy1) in BLOCKS.items():
        x0, x1, y0, y1 = int(fx0 * W), int(fx1 * W), int(fy0 * H), int(fy1 * H)
        sl = (slice(y0, y1), slice(x0, x1))
        bands, okk, plk, labk = ds[(slice(None), *sl)], ok[sl], plots[sl], lab[sl]
        tr = transform * rasterio.Affine.translation(x0, y0)
        patches = SCENARIOS.get(key, [])
        seed = sum(ord(ch) * (31 ** i) for i, ch in enumerate(key)) % 100000
        now_b, now_t = inject_stress(bands, plk, gsd, patches, "now", seed) if patches else (bands, None)
        name = f"healthy_site_block_{key}"
        planted = [asdict(p) for p in patches]
        info[key] = _write(out_root / f"sim_{key}", now_b, labk, okk, tr, crs, gsd, name, planted, now_t, bool(patches)) | {"patches": len(patches)}
        if any(p.earlier for p in patches) or (key == "c"):  # farms with an earlier survey on record
            earlier = [p for p in patches if p.earlier]
            prev_b, prev_t = inject_stress(bands, plk, gsd, patches, "earlier", seed) if earlier else (bands, None)
            _write(out_root / f"sim_{key}_prev", prev_b, labk, okk, tr, crs, gsd, name, [asdict(p) for p in earlier], prev_t, bool(earlier))
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
