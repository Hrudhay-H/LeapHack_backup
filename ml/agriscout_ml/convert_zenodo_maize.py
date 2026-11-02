"""Convert the Zenodo UAV maize orthomosaics (v2.1, doi:10.5281/zenodo.22062459) to our survey layout.

Source band order (verified in the dataset's v2.1 correction note): blue, green, red, red-edge, NIR, alpha.
Output: rgb.tif (pseudo-RGB from B/G/R reflectance), multispectral.tif (red, green, rededge, nir),
field_mask.tif (alpha > 0) and survey.json, downsampled to `gsd_m`.

  python -m agriscout_ml.convert_zenodo_maize SRC.tif OUT_DIR [--gsd 0.05]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import Affine


def convert(src_path: Path, out_dir: Path, gsd_m: float = 0.05) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    with rasterio.open(src_path) as src:
        scale = gsd_m / src.res[0]
        w, h = int(src.width / scale), int(src.height / scale)
        a = src.read(out_shape=(src.count, h, w), resampling=Resampling.average)
        t = src.transform * Affine.scale(src.width / w, src.height / h)
        crs = src.crs
    blue, green, red, rededge, nir, alpha = a
    # Alpha is ~1 on the survey and ~0 (water mosaic) or ~0.005 (rust mosaic) on the background.
    # The metadata's -10000 nodata value is not actually used in the pixel data.
    valid = alpha > 0.5
    hi = float(np.percentile(np.stack([red, green, blue])[:, valid], 99))
    rgb = (np.clip(np.stack([red, green, blue]) / hi, 0, 1) * 255).astype(np.uint8)
    rgb[:, ~valid] = 0
    ms = np.stack([red, green, rededge, nir]).astype(np.float32)
    ms[:, ~valid] = np.nan

    meta = dict(driver="GTiff", height=h, width=w, crs=crs, transform=t, compress="deflate")
    with rasterio.open(out_dir / "rgb.tif", "w", count=3, dtype="uint8", **meta) as d:
        d.write(rgb)
    with rasterio.open(out_dir / "multispectral.tif", "w", count=4, dtype="float32", nodata=np.nan, **meta) as d:
        d.write(ms)
        d.descriptions = ("red", "green", "rededge", "nir")
    with rasterio.open(out_dir / "field_mask.tif", "w", count=1, dtype="uint8", **meta) as d:
        d.write(valid.astype(np.uint8)[None])
    info = {
        "data_source": "zenodo_maize_2025",
        "crop": "maize",
        "source": src_path.name,
        "doi": "10.5281/zenodo.22062459",
        "license": "CC-BY-4.0",
        "attribution": "Suiçmez, Yilmaz & Kahraman (2026), UAV-Based Multispectral Maize Dataset (v2.1), Zenodo, CC BY 4.0",
        "gsd_m": gsd_m,
        "reflectance_calibrated": True,
        "note": "RGB is pseudo-RGB built from the blue/green/red multispectral bands.",
    }
    (out_dir / "survey.json").write_text(json.dumps(info, indent=2))
    return {**info, "size_px": [w, h], "valid_fraction": float(valid.mean())}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--gsd", type=float, default=0.05)
    a = ap.parse_args()
    print(json.dumps(convert(a.src, a.out, a.gsd), indent=2))
