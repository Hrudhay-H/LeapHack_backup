"""Survey loading with explicit common-grid alignment and basic quality checks."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import Affine, from_origin
from rasterio.warp import reproject

BANDS = ["red", "green", "rededge", "nir"]


@dataclass
class Survey:
    rgb: np.ndarray  # (3, H, W) uint8
    ms: np.ndarray | None  # (4, H, W) float32 reflectance; NaN where invalid; None for RGB-only surveys
    field_mask: np.ndarray  # (H, W) bool, inside the field boundary
    transform: Affine
    crs: str
    gsd_m: float
    meta: dict = field(default_factory=dict)
    quality: dict = field(default_factory=dict)

    @property
    def shape(self) -> tuple[int, int]:
        return self.rgb.shape[1:]


def _to_grid(path: Path, band: int | None, shape, transform, crs, resampling, dtype) -> np.ndarray:
    """Warp one or all bands of a raster onto the target grid."""
    with rasterio.open(path) as src:
        idx = [band] if band else list(range(1, src.count + 1))
        out = np.full((len(idx), *shape), np.nan if np.issubdtype(dtype, np.floating) else 0, dtype=dtype)
        for k, b in enumerate(idx):
            reproject(
                source=rasterio.band(src, b),
                destination=out[k],
                dst_transform=transform,
                dst_crs=crs,
                resampling=resampling,
            )
    return out


def load_survey(directory: Path, target_gsd_m: float | None = 0.05) -> Survey:
    """Load rgb.tif (+ optional multispectral.tif and field_mask.tif) onto one grid.

    With a multispectral raster the grid is the intersection of both rasters in the RGB CRS; both sources
    are warped, so mismatched resolutions/CRSs are aligned rather than assumed equal. Without one the
    survey is RGB-only (ms is None) and the vegetation-index branch falls back to VARI.
    """
    directory = Path(directory)
    rgb_path, ms_path = directory / "rgb.tif", directory / "multispectral.tif"
    if not rgb_path.exists():
        raise FileNotFoundError(f"missing required raster: {rgb_path}")
    has_ms = ms_path.exists()

    from rasterio.warp import transform_bounds

    with rasterio.open(rgb_path) as r:
        if r.crs is None:
            raise ValueError("rasters must be georeferenced (missing CRS)")
        if not r.crs.is_projected:
            raise ValueError("RGB CRS must be projected (metres); reproject it first")
        crs = r.crs
        left, bottom, right, top = r.bounds
        native = r.res[0]
    ms_desc: list = []
    if has_ms:
        with rasterio.open(ms_path) as m:
            if m.crs is None:
                raise ValueError("rasters must be georeferenced (missing CRS)")
            if m.count < 4:
                raise ValueError(f"multispectral raster needs 4 bands (R,G,RE,NIR); found {m.count}")
            mb = transform_bounds(m.crs, crs, *m.bounds)
            ms_desc = list(m.descriptions)
        left, bottom = max(left, mb[0]), max(bottom, mb[1])
        right, top = min(right, mb[2]), min(top, mb[3])
        if right <= left or top <= bottom:
            raise ValueError("RGB and multispectral rasters do not overlap")
    gsd = max(target_gsd_m, native) if target_gsd_m else native
    w = int((right - left) / gsd)
    h = int((top - bottom) / gsd)
    transform = from_origin(left, top, gsd, gsd)

    shape = (h, w)
    rgb = _to_grid(rgb_path, None, shape, transform, crs, Resampling.average, np.float32)[:3]
    ms = _to_grid(ms_path, None, shape, transform, crs, Resampling.bilinear, np.float32)[:4] if has_ms else None
    rgb = np.nan_to_num(rgb, nan=0).clip(0, 255).astype(np.uint8)

    fm_path = directory / "field_mask.tif"
    if fm_path.exists():
        field_mask = _to_grid(fm_path, 1, shape, transform, crs, Resampling.nearest, np.uint8)[0] > 0
    else:
        field_mask = np.ones(shape, dtype=bool)

    meta = {}
    sj = directory / "survey.json"
    if sj.exists():
        meta = json.loads(sj.read_text())

    nodata = rgb.sum(axis=0) == 0
    if ms is not None:
        nodata |= ~np.isfinite(ms).all(axis=0)
    sat = (rgb >= 250).all(axis=0)
    # Quality is judged inside the supplied field boundary: the empty corners of an
    # irregular orthomosaic are outside the field, not defects in it.
    inside = field_mask.copy()
    n_inside = max(int(inside.sum()), 1)
    quality = {
        "modality": "RGB_MULTISPECTRAL" if has_ms else "RGB_ONLY",
        "nodata_fraction": float((nodata & inside).sum() / n_inside),
        "saturated_fraction": float((sat & inside).sum() / n_inside),
        "band_descriptions": ms_desc,
        "reflectance_calibrated": bool(meta.get("reflectance_calibrated", False)),
        "alignment": "warped_to_common_grid",
    }
    if ms is not None:
        quality["ms_value_range"] = [float(np.nanmin(ms)), float(np.nanmax(ms))]
        # Reflectance sanity check: raw DN values (0..65535) must not be used as-is.
        quality["looks_like_reflectance"] = quality["ms_value_range"][1] <= 1.5
    field_mask &= ~nodata

    return Survey(rgb, ms, field_mask, transform, str(crs), float(gsd), meta, quality)
