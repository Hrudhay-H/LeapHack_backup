"""Stitch the Thai UAV bacterial-leaf-blight patches into georeferenced orthomosaic surveys.

The dataset ships 256x256 patches (1.1 cm, 5 bands B,G,R,RedEdge,NIR) with a 50% overlap and per-patch
coordinates, plus expert label masks (1 others, 2 low blight, 3 high blight, 4 healthy). Patches are placed at
their exact pixel offsets, block-averaged by `factor`, and written as a survey folder
(rgb.tif, multispectral.tif, field_mask.tif, expert_mask.tif, survey.json).

Patch positions come from data/raw/blb/positions.json + cluster.npy (see ml/experiments/blb_eval.py):
cluster 1 = healthy site, cluster 0 = blight site.

  python -m agriscout_ml.mosaic_blb SITE OUT_DIR [--window x0 y0 x1 y1] [--factor 4]
  (window in metres from the site's top-left corner)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

ROOT = Path("data/raw/blb")
D1 = ROOT / "data/D1"
ATTRIBUTION = (
    "Logavitool, Intarat & Thapa (2025), BLB UAV Dataset (bacterial leaf blight in paddy rice, DJI Phantom 4 Multispectral), "
    "figshare, doi 10.6084/m9.figshare.26955862, CC BY 4.0"
)
SITE_NAME = {0: "blight_site", 1: "healthy_site"}


def build_site(site: int, factor: int = 4):
    rows = json.load(open(ROOT / "positions.json"))
    cluster = np.load(ROOT / "cluster.npy")
    idx = np.flatnonzero(cluster == site)
    bounds = []
    for i in idx:
        with rasterio.open(D1 / rows[i][0] / rows[i][1]) as s:
            bounds.append((s.bounds.left, s.bounds.top, s.res[0], s.crs))
    res = bounds[0][2]
    crs = bounds[0][3]
    left0 = min(b[0] for b in bounds)
    top0 = max(b[1] for b in bounds)
    px = [(round((b[0] - left0) / res), round((top0 - b[1]) / res)) for b in bounds]
    W = max(p[0] for p in px) + 256
    H = max(p[1] for p in px) + 256
    W, H = W // factor * factor, H // factor * factor
    bands = np.zeros((5, H, W), np.float32)
    label = np.zeros((H, W), np.uint8)
    have = np.zeros((H, W), bool)
    for i, (x, y) in zip(idx, px):
        sp, name = rows[i][0], rows[i][1]
        with rasterio.open(D1 / sp / name) as s:
            b = s.read().astype(np.float32)
        with rasterio.open(D1 / f"{sp}_labels" / name.replace("image_patch", "label_patch")) as s:
            m = np.rint(s.read(1)).astype(np.uint8)
        h, w = min(256, H - y), min(256, W - x)
        valid = b.sum(axis=0)[:h, :w] > 0
        sl = (slice(y, y + h), slice(x, x + w))
        bands[(slice(None), *sl)] = np.where(valid, b[:, :h, :w], bands[(slice(None), *sl)])
        label[sl] = np.where(valid, m[:h, :w], label[sl])
        have[sl] |= valid
    # block-average (nodata-aware) and mode-ish label downsample
    f = factor
    hh, ww = H // f, W // f
    cnt = have.reshape(hh, f, ww, f).sum(axis=(1, 3))
    ok = cnt >= (f * f) // 2
    ds = (bands * have).reshape(5, hh, f, ww, f).sum(axis=(2, 4)) / np.maximum(cnt, 1)
    lab = label.reshape(hh, f, ww, f).transpose(0, 2, 1, 3).reshape(hh, ww, f * f)
    counts = np.stack([(lab == k).sum(-1) for k in range(5)])
    lab_ds = counts.argmax(0).astype(np.uint8)
    lab_ds[~ok] = 0
    ds[:, ~ok] = 0
    transform = from_origin(left0, top0, res * f, res * f)
    return ds, lab_ds, ok, transform, crs, res * f


def write_survey(ds, lab, ok, transform, crs, gsd, out: Path, window=None, name="", site_label="") -> dict:
    out.mkdir(parents=True, exist_ok=True)
    if window:
        x0, y0, x1, y1 = [int(round(v / gsd)) for v in window]
        ds, lab, ok = ds[:, y0:y1, x0:x1], lab[y0:y1, x0:x1], ok[y0:y1, x0:x1]
        transform = transform * rasterio.Affine.translation(x0, y0)
    # drop empty rows/cols around the footprint
    ys, xs = np.nonzero(ok)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    ds, lab, ok = ds[:, y0:y1, x0:x1], lab[y0:y1, x0:x1], ok[y0:y1, x0:x1]
    transform = transform * rasterio.Affine.translation(x0, y0)
    blue, green, red, rededge, nir = ds
    # Fixed global gain (not per-image) so absolute colour is comparable between surveys.
    rgb = (np.clip(np.stack([red, green, blue]) / 0.6, 0, 1) * 255).astype(np.uint8)
    rgb[:, ~ok] = 0
    ms = np.stack([red, green, rededge, nir]).astype(np.float32)
    ms[:, ~ok] = np.nan
    h, w = ok.shape
    meta = dict(driver="GTiff", height=h, width=w, crs=crs, transform=transform, compress="deflate")
    with rasterio.open(out / "rgb.tif", "w", count=3, dtype="uint8", **meta) as d:
        d.write(rgb)
    with rasterio.open(out / "multispectral.tif", "w", count=4, dtype="float32", nodata=np.nan, **meta) as d:
        d.write(ms)
        d.descriptions = ("red", "green", "rededge", "nir")
    with rasterio.open(out / "field_mask.tif", "w", count=1, dtype="uint8", **meta) as d:
        d.write(ok.astype(np.uint8)[None])
    with rasterio.open(out / "expert_mask.tif", "w", count=1, dtype="uint8", **meta) as d:
        d.write(lab[None])
    info = {
        "data_source": "blb_thai_uav",
        "crop": "paddy",
        "site": site_label,
        "source": name,
        "doi": "10.6084/m9.figshare.26955862",
        "license": "CC-BY-4.0",
        "attribution": ATTRIBUTION,
        "gsd_m": float(gsd),
        # The authors describe the bands as pre-processed but do not state radiometric calibration.
        "reflectance_calibrated": False,
        "note": "Mosaic stitched from 256 px dataset patches; RGB is pseudo-RGB from the red/green/blue bands. Expert labels are subplot-level severity scores.",
    }
    (out / "survey.json").write_text(json.dumps(info, indent=2))
    u, c = np.unique(lab[ok], return_counts=True)
    return {**info, "size_px": [w, h], "area_m2": round(float(ok.sum() * gsd**2), 1),
            "label_share": {int(k): round(float(v / ok.sum()), 3) for k, v in zip(u, c)}}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("site", type=int, choices=[0, 1])
    ap.add_argument("out", type=Path)
    ap.add_argument("--window", type=float, nargs=4)
    ap.add_argument("--factor", type=int, default=4)
    a = ap.parse_args()
    ds, lab, ok, tr, crs, gsd = build_site(a.site, a.factor)
    print(json.dumps(write_survey(ds, lab, ok, tr, crs, gsd, a.out, a.window, SITE_NAME[a.site], SITE_NAME[a.site]), indent=2))
